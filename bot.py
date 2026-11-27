"""Robô de operação — mercado à vista (spot), só compra (sem alavancagem, sem venda a descoberto).

Uso:
  py -3.13 bot.py            # fica rodando (no seu PC)
  py -3.13 bot.py --uma-vez  # roda um ciclo e sai (é assim que o GitHub Actions usa)

O modo vem do config.yaml (paper | demo | testnet | real).
  demo = conta Demo Trading oficial da corretora (OKX ou Binance): você acompanha as ordens no app.

Travas de segurança:
  - modo real só roda com CONFIRMAR_REAL=SIM no .env;
  - limite de perda diária e de trades por dia;
  - teto de capital (risco.capital_maximo);
  - pausa: arquivo PARAR na pasta, ou "bot: pausado: true" no config.yaml -> não abre novas
    operações (continua cuidando do stop/alvo da posição aberta).

IMPORTANTE: o stop e o alvo são vigiados pelo próprio robô. Se o robô estiver
desligado, a posição aberta fica SEM proteção. Para operar de verdade, rode num VPS.
"""
import argparse
import copy
import logging
import os
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from dotenv import load_dotenv

from armazenamento import criar_armazenamento
from configuracao import PASTA, carregar_config
from estrategia import aquecimento, atualizar_trailing, calcular_indicadores, niveis_saida
from risco import aplicar_teto_capital, limites_do_dia_em_reais, pode_operar_hoje, tamanho_posicao

ARQ_PARAR = os.path.join(PASTA, "PARAR")
log = logging.getLogger("robo")


def configurar_log(armazenamento):
    log.setLevel(logging.INFO)
    log.handlers.clear()
    tela = logging.StreamHandler(sys.stdout)
    tela.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
    log.addHandler(tela)
    log.addHandler(armazenamento.handler_log())


# ================================================================ corretoras
class Corretora:
    """Conexão real com a exchange (testnet ou conta real) via ccxt."""

    def __init__(self, cfg):
        import ccxt

        self.cfg, self.par = cfg, cfg["par"]
        opcoes = {"enableRateLimit": True, "options": {"defaultType": "spot"}}
        prefixo = {"demo": "DEMO_", "testnet": "TESTNET_", "real": ""}.get(cfg["modo"])
        if prefixo is not None:
            opcoes.update(apiKey=os.getenv(prefixo + "API_KEY"), secret=os.getenv(prefixo + "API_SECRET"),
                          password=os.getenv(prefixo + "API_PASSWORD") or None)  # OKX exige a passphrase
        self.ex = getattr(ccxt, cfg["exchange"])(opcoes)
        if cfg["modo"] == "demo":
            if cfg["exchange"] == "binance":
                self.ex.enable_demo_trading(True)   # Binance Demo Trading
            else:
                self.ex.set_sandbox_mode(True)      # OKX: conta Demo Trading
        elif cfg["modo"] == "testnet":
            self.ex.set_sandbox_mode(True)
        if cfg["modo"] != "paper" and not self.ex.apiKey:
            sys.exit("Faltam as chaves de API no arquivo .env para o modo " + cfg["modo"])
        self.ex.load_markets()
        mercado = self.ex.market(self.par)
        self.base, self.cotacao = mercado["base"], mercado["quote"]
        self.custo_minimo = ((mercado.get("limits") or {}).get("cost") or {}).get("min") or 0
        self.tf_ms = self.ex.parse_timeframe(cfg["timeframe"]) * 1000

    def candles_fechados(self, limite=1000):
        dados = self.ex.fetch_ohlcv(self.par, self.cfg["timeframe"], limit=limite)
        df = pd.DataFrame(dados, columns=["timestamp", "open", "high", "low", "close", "volume"])
        agora_ms = self.ex.milliseconds()
        df = df[df["timestamp"] + self.tf_ms <= agora_ms]  # descarta o candle ainda em formação
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        return df.set_index("timestamp").astype(float)

    def preco(self):
        return float(self.ex.fetch_ticker(self.par)["last"])

    def saldos(self):
        livre = self.ex.fetch_balance().get("free", {})
        return float(livre.get(self.cotacao) or 0), float(livre.get(self.base) or 0)

    def comprar(self, qtd):
        qtd = float(self.ex.amount_to_precision(self.par, qtd))
        return self._executado(self.ex.create_market_buy_order(self.par, qtd), qtd)

    def vender(self, qtd):
        qtd = float(self.ex.amount_to_precision(self.par, qtd))
        return self._executado(self.ex.create_market_sell_order(self.par, qtd), qtd)

    def _executado(self, ordem, qtd):
        preco = ordem.get("average") or ordem.get("price") or self.preco()
        return float(ordem.get("filled") or qtd), float(preco)


class CorretoraPaper(Corretora):
    """Usa preços reais, mas as ordens são simuladas numa carteira local."""

    def __init__(self, cfg, carteira):
        super().__init__(cfg)
        self.carteira = carteira
        self.taxa, self.slip = cfg["custos"]["taxa"], cfg["custos"]["slippage"]

    def saldos(self):
        return self.carteira["cotacao"], self.carteira["base"]

    def comprar(self, qtd):
        preco = float(self.preco()) * (1 + self.slip)
        qtd = min(float(qtd), self.carteira["cotacao"] / (preco * (1 + self.taxa)))
        self.carteira["cotacao"] -= qtd * preco * (1 + self.taxa)
        self.carteira["base"] += qtd
        return qtd, preco

    def vender(self, qtd):
        qtd = min(float(qtd), self.carteira["base"])
        preco = float(self.preco()) * (1 - self.slip)
        self.carteira["cotacao"] += qtd * preco * (1 - self.taxa)
        self.carteira["base"] -= qtd
        return qtd, preco


# ================================================================ expediente
def fase_expediente(cfg, agora):
    """'aberto' | 'almoco' | 'fechado' conforme o bloco "horario" do config (None = opera 24 h)."""
    h = cfg.get("horario")
    if not h:
        return None
    local = agora.astimezone(ZoneInfo(h.get("fuso", "America/Sao_Paulo")))
    minuto = local.hour * 60 + local.minute
    m = lambda txt: int(txt[:2]) * 60 + int(txt[3:5])
    if minuto < m(h["inicio"]) or minuto >= m(h["fim"]):
        return "fechado"
    almoco = h.get("almoco")
    if almoco and m(almoco[0]) <= minuto < m(almoco[1]):
        return "almoco"
    return "aberto"


# ================================================================ robô
class Robo:
    def __init__(self, cfg, corretora=None, armazenamento=None, pnl_total_dia=None):
        self.cfg, self.est, self.risco = cfg, cfg["estrategia"], cfg["risco"]
        self.rotulo = cfg.get("rotulo", cfg["modo"])
        self.pnl_total_dia = pnl_total_dia or (lambda: self.estado["pnl_dia"])
        self.taxa = cfg["custos"]["taxa"]
        self.arm = armazenamento or criar_armazenamento(self.rotulo)
        self.ultimo_preco = None
        self.fase = None
        self.estado = self._carregar_estado()
        if corretora is not None:
            self.corretora = corretora
        elif cfg["modo"] == "paper":
            self.corretora = CorretoraPaper(cfg, self.estado["carteira_paper"])
        else:
            self.corretora = Corretora(cfg)
        self._reconciliar()

    # ---------- estado persistente (sobrevive a reinício)
    def _carregar_estado(self):
        salvo = self.arm.ler("estado")
        if salvo:
            return salvo
        return {
            "posicao": None, "dia": None, "pnl_dia": 0.0, "trades_dia": 0,
            "capital_inicio_dia": 0.0, "ultimo_candle": 0,
            "carteira_paper": {"cotacao": float(self.cfg["paper"]["saldo_inicial"]), "base": 0.0},
        }

    def pausado(self):
        if os.path.exists(ARQ_PARAR) or self.cfg["bot"].get("pausado"):
            return True
        try:  # botão "Pausar" do painel admin
            controle = self.arm.ler_global("controle") or {}
            return bool(controle.get("pausado"))
        except Exception:
            return False

    def salvar(self):
        self.arm.gravar("estado", self.estado)
        self._gravar_status()
        self.arm.descarregar()

    def _gravar_status(self):
        """Lido pelo painel."""
        try:
            if self.ultimo_preco is None:
                return
            cotacao, _ = self.corretora.saldos()
            self.arm.gravar("status", {
                "atualizado_em": datetime.now(timezone.utc).isoformat(),
                "rotulo": self.rotulo, "pnl_total_dia": self.pnl_total_dia(),
                "modo": self.cfg["modo"], "exchange": self.cfg["exchange"], "par": self.cfg["par"],
                "timeframe": self.cfg["timeframe"], "estrategia": self.est["tipo"], "risco": self.risco,
                "intervalo_esperado_seg": self.cfg["bot"].get("intervalo_esperado_seg", 120),
                "preco": self.ultimo_preco, "saldo_livre": cotacao, "patrimonio": self.capital(self.ultimo_preco),
                "posicao": self.estado["posicao"], "pnl_dia": self.estado["pnl_dia"],
                "grafico": self.estado.get("grafico"),
                "trades_dia": self.estado["trades_dia"], "parado": self.pausado(),
                "expediente": self.fase, "horario": self.cfg.get("horario"),
                "valor_fixo_reais": self.risco.get("valor_fixo_reais") or 0,
                "saldo_inicial": float(self.cfg["paper"]["saldo_inicial"]) if self.cfg["modo"] == "paper" else None,
            })
        except Exception as e:
            log.warning(f"Não consegui atualizar o status do painel: {e}")

    def _registrar_patrimonio(self, quando, preco):
        self.arm.registrar_patrimonio({"timestamp": quando.isoformat(), "preco": round(preco, 2),
                                       "patrimonio": round(self.capital(preco), 4)})

    def _reconciliar(self):
        """Se o estado diz que há posição, mas a moeda não está na conta, limpa o estado."""
        pos = self.estado["posicao"]
        if pos and self.cfg["modo"] != "paper":
            _, base = self.corretora.saldos()
            if base < pos["qtd"] * 0.5:
                log.warning("Estado tinha posição aberta, mas o saldo não confere. Limpando o estado.")
                self.estado["posicao"] = None

    # ---------- utilidades
    def capital(self, preco):
        cotacao, _ = self.corretora.saldos()
        pos = self.estado["posicao"]
        return cotacao + (pos["qtd"] * preco if pos else 0)

    def _virar_dia(self, agora, preco):
        hoje = agora.strftime("%Y-%m-%d")
        if self.estado["dia"] != hoje:
            self.estado.update(dia=hoje, pnl_dia=0.0, trades_dia=0,
                               capital_inicio_dia=aplicar_teto_capital(self.capital(preco), self.risco))
            log.info(f"Novo dia {hoje}. Capital de referência: {self.estado['capital_inicio_dia']:.2f}")

    def _registrar_trade(self, linha):
        try:
            self.arm.registrar_trade(linha)
        except Exception as e:
            log.error(f"Não consegui registrar a operação: {e}")

    def _guardar_grafico(self, df):
        """Dados do gráfico para o painel e a sala (últimos 200 candles)."""
        col = "mm" if "mm" in df.columns else ("ema_lenta" if "ema_lenta" in df.columns else "ema_tendencia")
        ult = df.tail(200)
        diario = str(self.cfg["timeframe"]).endswith("d")
        fmt = (lambda ts: ts.strftime("%Y-%m-%d")) if diario else (lambda ts: ts.strftime("%Y-%m-%dT%H:%M:00Z"))
        lista = lambda serie: [None if pd.isna(x) else round(float(x), 2) for x in serie]
        nomes = {"mm": f"Média {self.est.get('mm_periodo', '')} dias", "ema_lenta": f"EMA {self.est.get('ema_lenta', '')}"}
        g = {
            "linha": nomes.get(col, "EMA tendência"),
            "t": [fmt(ts) for ts in ult.index],
            "preco": [round(float(x), 2) for x in ult["close"]],
            "media": lista(ult[col]),
            "banda": float(self.est.get("mm_banda", 0.0)) if col == "mm" else 0.0,
        }
        if "ema_rapida" in ult.columns:
            g["rapida"] = lista(ult["ema_rapida"])
            g["linha_rapida"] = f"EMA {self.est.get('ema_rapida', '')}"
        ultimo = ult.iloc[-1]
        g["ind"] = {k: (None if pd.isna(ultimo[k]) else round(float(ultimo[k]), 2))
                    for k in ("ema_tendencia", "rsi", "atr") if k in ult.columns}
        g["regras"] = {k: self.est.get(k) for k in ("tipo", "ema_rapida", "ema_lenta", "ema_tendencia", "rsi_min", "rsi_max", "stop_atr")}
        self.estado["grafico"] = g

    # ---------- ordens
    def abrir(self, valor_atr):
        preco = self.corretora.preco()
        stop, _ = niveis_saida(preco, valor_atr, self.est)
        cotacao, _ = self.corretora.saldos()
        capital = aplicar_teto_capital(cotacao, self.risco)
        fixo = float(self.risco.get("valor_fixo_reais") or 0)
        if fixo > 0:  # valor fixo por operação (ex.: R$ 1), limitado ao saldo disponível
            qtd = min(fixo, capital) / preco * (1 - self.taxa)
        else:
            qtd = tamanho_posicao(capital, preco, stop, self.risco)
        if qtd * preco < max(self.corretora.custo_minimo, 1e-9):
            log.warning(f"Ordem de {qtd * preco:.2f} abaixo do mínimo da exchange ({self.corretora.custo_minimo}). Pulando.")
            return
        qtd_exec, preco_exec = self.corretora.comprar(qtd)
        stop, alvo = niveis_saida(preco_exec, valor_atr, self.est)  # recalcula com o preço executado
        self.estado["posicao"] = {
            "qtd": qtd_exec, "entrada": preco_exec, "stop": stop, "alvo": alvo,
            "custo": qtd_exec * preco_exec * (1 + self.taxa),
            "quando": datetime.now(timezone.utc).isoformat(),
        }
        self.estado["trades_dia"] += 1
        alvo_txt = f"{alvo:.2f}" if alvo else "sem alvo"
        log.info(f"[{self.cfg['par']}] COMPRA {qtd_exec:.6f} a {preco_exec:.2f} | stop {stop:.2f} | alvo {alvo_txt}")

    def fechar(self, motivo):
        pos = self.estado["posicao"]
        _, base_livre = self.corretora.saldos()
        qtd = min(pos["qtd"], base_livre)  # a taxa às vezes é cobrada na própria moeda
        preco_ref = self.corretora.preco()
        if qtd * preco_ref < self.corretora.custo_minimo:
            log.warning("Saldo restante abaixo do mínimo da exchange (poeira). Encerrando posição no estado.")
            self.estado["posicao"] = None
            return
        qtd_exec, preco_exec = self.corretora.vender(qtd)
        lucro = qtd_exec * preco_exec * (1 - self.taxa) - pos["custo"]
        self.estado["pnl_dia"] += lucro
        self.estado["posicao"] = None
        log.info(f"[{self.cfg['par']}] VENDA ({motivo}) {qtd_exec:.6f} a {preco_exec:.2f} | resultado {lucro:+.2f}")
        self._registrar_trade({
            "entrada_em": pos["quando"], "saida_em": datetime.now(timezone.utc).isoformat(),
            "preco_entrada": pos["entrada"], "preco_saida": preco_exec, "qtd": qtd_exec,
            "lucro": round(lucro, 4), "motivo": motivo,
        })

    # ---------- ciclo principal
    def ciclo(self, agora=None):
        agora = agora or datetime.now(timezone.utc)
        preco = self.corretora.preco()
        self.ultimo_preco = float(preco)
        self._virar_dia(agora, preco)

        # 1) vigia stop/alvo a cada ciclo
        pos = self.estado["posicao"]
        if pos:
            if preco <= pos["stop"]:
                self.fechar("stop")
            elif pos["alvo"] is not None and preco >= pos["alvo"]:
                self.fechar("alvo")

        # 1b) expediente: fora do horário não abre nada; às 18h encerra a posição do dia
        self.fase = fase_expediente(self.cfg, agora)
        pos = self.estado["posicao"]
        if pos and self.fase == "fechado" and (self.cfg.get("horario") or {}).get("fechar_no_fim", True):
            log.info(f"[{self.cfg['par']}] Fim do expediente: encerrando a posição do dia.")
            self.fechar("fim do expediente")

        # 2) estratégia só roda quando fecha um candle novo
        tf = self.corretora.tf_ms
        ultimo_fechado = int(agora.timestamp() * 1000) // tf * tf - tf
        if ultimo_fechado <= self.estado["ultimo_candle"]:
            if not self.estado.get("grafico") or "banda" not in self.estado["grafico"]:  # monta/atualiza o gráfico sem reprocessar sinais
                self._guardar_grafico(calcular_indicadores(self.corretora.candles_fechados(), self.est))
            return
        df = calcular_indicadores(self.corretora.candles_fechados(), self.est)
        if len(df) < aquecimento(self.est) or int(df.index[-1].timestamp() * 1000) < ultimo_fechado:
            return  # exchange ainda não entregou o candle; tenta no próximo ciclo
        self.estado["ultimo_candle"] = ultimo_fechado
        c = df.iloc[-1]
        self._guardar_grafico(df)
        self._registrar_patrimonio(df.index[-1], float(c["close"]))
        log.info(f"[{self.cfg['par']}] Candle {df.index[-1]:%Y-%m-%d %H:%M} | fecha {c['close']:.2f} | ATR {c['atr']:.2f} | "
                 f"tendência {'alta' if c['close'] > c['ema_tendencia'] else 'baixa'}")

        pos = self.estado["posicao"]
        if pos:
            novo_stop = float(atualizar_trailing(pos["stop"], float(c["close"]), float(c["atr"]), self.est))
            if novo_stop > pos["stop"]:
                log.info(f"Stop móvel subiu: {pos['stop']:.2f} -> {novo_stop:.2f}")
                pos["stop"] = novo_stop
            if c["saida"]:
                self.fechar("sinal de saída")
            return

        if not c["entrada"]:
            return
        if self.fase in ("almoco", "fechado"):
            log.info(f"[{self.cfg['par']}] Sinal de compra ignorado: {'horário de almoço' if self.fase == 'almoco' else 'fora do expediente'}.")
            return
        if self.pausado():
            log.info("Sinal de compra ignorado: robô pausado.")
            return
        ok, motivo = pode_operar_hoje(self.estado["pnl_dia"], self.estado["capital_inicio_dia"],
                                      self.estado["trades_dia"], self.risco)
        if ok:
            ok, motivo = limites_do_dia_em_reais(self.pnl_total_dia(), self.risco)
        if not ok:
            log.info(f"[{self.cfg['par']}] Sinal de compra ignorado: {motivo}.")
            return
        self.abrir(float(c["atr"]))

    def ciclo_protegido(self):
        import ccxt
        try:
            self.ciclo()
        except ccxt.NetworkError as e:
            log.warning(f"Falha de rede, tento de novo no próximo ciclo: {e}")
        except ccxt.ExchangeError as e:
            log.error(f"Erro da corretora: {e}")
        except Exception:
            log.exception("Erro inesperado")
        self.salvar()

    def executar(self):
        log.info(f"Robô iniciado | modo {self.cfg['modo'].upper()} | {self.cfg['exchange']} {self.cfg['par']} {self.cfg['timeframe']}")
        intervalo = self.cfg["bot"]["intervalo_checagem_seg"]
        try:
            while True:
                self.ciclo_protegido()
                time.sleep(intervalo)
        except KeyboardInterrupt:
            self.salvar()
            if self.estado["posicao"]:
                log.warning("Robô parado COM posição aberta. O stop não está mais sendo vigiado!")
            log.info("Robô parado.")


def montar_mercados(cfg):
    """Um config por mercado. Sem a lista 'pares', usa o 'par' único (compatível com versões antigas)."""
    pares = cfg.get("pares") or [{"par": cfg["par"]}]
    saida = []
    for p in pares:
        c = copy.deepcopy(cfg)
        c["par"] = p["par"]
        c["modo"] = p.get("modo", cfg["modo"])
        if "capital_maximo" in p:
            c["risco"]["capital_maximo"] = p["capital_maximo"]
            c["paper"]["saldo_inicial"] = p["capital_maximo"]
        c["rotulo"] = f"{c['modo']}-{p['par'].replace('/', '')}"
        saida.append(c)
    return saida


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--uma-vez", action="store_true", help="roda um ciclo de cada mercado e sai (GitHub Actions)")
    args = p.parse_args()

    load_dotenv(os.path.join(PASTA, ".env"))
    cfg = carregar_config()
    mercados = montar_mercados(cfg)
    if any(m["modo"] == "real" for m in mercados) and os.getenv("CONFIRMAR_REAL") != "SIM":
        sys.exit("Modo REAL bloqueado. Para liberar, defina CONFIRMAR_REAL=SIM (.env ou segredo do GitHub).")
    if args.uma_vez:
        for m in mercados:
            m["bot"]["intervalo_esperado_seg"] = m["bot"].get("intervalo_nuvem_seg", 900)

    log.setLevel(logging.INFO)
    log.handlers.clear()
    tela = logging.StreamHandler(sys.stdout)
    tela.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
    log.addHandler(tela)

    robos = []

    def pnl_total(modo):
        return lambda: sum(r.estado["pnl_dia"] for r in robos if r.cfg["modo"] == modo)

    for m in mercados:
        arm = criar_armazenamento(m["rotulo"])
        h = arm.handler_log()
        h.addFilter(lambda rec, par=m["par"]: f"[{par}]" in rec.getMessage() or "[" not in rec.getMessage())
        log.addHandler(h)
        robos.append(Robo(m, armazenamento=arm, pnl_total_dia=pnl_total(m["modo"])))
    log.info("Mercados: " + ", ".join(f"{r.cfg['par']} ({r.cfg['modo']}, até {r.risco.get('capital_maximo')})" for r in robos))

    if args.uma_vez:
        for r in robos:
            r.ciclo_protegido()
            log.info(f"[{r.cfg['par']}] Ciclo concluído | preço {r.ultimo_preco} | "
                     f"posição {'aberta' if r.estado['posicao'] else 'nenhuma'}")
            r.arm.descarregar()
        return

    intervalo = cfg["bot"]["intervalo_checagem_seg"]
    try:
        while True:
            for r in robos:
                r.ciclo_protegido()
            time.sleep(intervalo)
    except KeyboardInterrupt:
        for r in robos:
            r.salvar()
        log.info("Robô parado.")


if __name__ == "__main__":
    main()
