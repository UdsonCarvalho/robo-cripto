"""Onde o robô guarda estado, status, operações, patrimônio e log.

- Local (padrão): arquivos na pasta do robô (estado_*.json e logs/).
- Supabase: se as variáveis SUPABASE_URL e SUPABASE_SERVICE_KEY existirem
  (é o que acontece no GitHub Actions). O painel online lê de lá.
"""
import csv
import json
import logging
import os
from datetime import datetime, timezone

from configuracao import PASTA


def agora_iso():
    return datetime.now(timezone.utc).isoformat()


def criar_armazenamento(modo):
    url, chave = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY")
    if url and chave:
        return ArmazenamentoSupabase(url, chave, modo)
    return ArmazenamentoLocal(modo)


class ArmazenamentoLocal:
    def __init__(self, modo):
        self.modo = modo
        self.logs = os.path.join(PASTA, "logs")
        os.makedirs(self.logs, exist_ok=True)
        self.arquivos_kv = {
            "estado": os.path.join(PASTA, f"estado_{modo}.json"),
            "status": os.path.join(self.logs, f"status_{modo}.json"),
        }

    def ler(self, chave):
        caminho = self.arquivos_kv[chave]
        if not os.path.exists(caminho):
            return None
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)

    def ler_global(self, chave):
        return None

    def gravar(self, chave, valor):
        caminho = self.arquivos_kv[chave]
        tmp = caminho + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(valor, f, indent=2, default=str)
        os.replace(tmp, caminho)

    def _anexar_csv(self, nome, linha):
        caminho = os.path.join(self.logs, f"{nome}_{self.modo}.csv")
        novo = not os.path.exists(caminho)
        with open(caminho, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(linha.keys()))
            if novo:
                w.writeheader()
            w.writerow(linha)

    def registrar_trade(self, linha):
        self._anexar_csv("trades", linha)

    def registrar_patrimonio(self, linha):
        self._anexar_csv("patrimonio", linha)

    def handler_log(self):
        h = logging.FileHandler(os.path.join(self.logs, f"bot_{self.modo}.log"), encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
        return h

    def descarregar(self):
        pass


class ArmazenamentoSupabase:
    """Grava via API REST do Supabase usando a chave service_role (só no servidor, nunca no painel)."""

    def __init__(self, url, chave, modo):
        import requests

        self.req = requests
        self.modo = modo
        self.base = url.rstrip("/") + "/rest/v1"
        self.cab = {"apikey": chave, "Content-Type": "application/json"}
        if chave.startswith("eyJ"):  # chave antiga (JWT service_role); as novas sb_secret_ vão só no apikey
            self.cab["Authorization"] = f"Bearer {chave}"
        self._logs_pendentes = []

    def _post(self, tabela, corpo, upsert=False):
        cab = dict(self.cab)
        if upsert:
            cab["Prefer"] = "resolution=merge-duplicates"
        r = self.req.post(f"{self.base}/{tabela}", headers=cab, data=json.dumps(corpo, default=str), timeout=20)
        r.raise_for_status()

    def ler(self, chave):
        r = self.req.get(f"{self.base}/robo_kv", headers=self.cab, timeout=20,
                         params={"chave": f"eq.{self.modo}:{chave}", "select": "valor"})
        r.raise_for_status()
        dados = r.json()
        return dados[0]["valor"] if dados else None

    def ler_global(self, chave):
        """Chave sem prefixo de modo (ex.: 'controle', gravada pelo painel admin)."""
        r = self.req.get(f"{self.base}/robo_kv", headers=self.cab, timeout=20,
                         params={"chave": f"eq.{chave}", "select": "valor"})
        r.raise_for_status()
        dados = r.json()
        return dados[0]["valor"] if dados else None

    def gravar(self, chave, valor):
        self._post("robo_kv", {"chave": f"{self.modo}:{chave}", "valor": valor, "atualizado_em": agora_iso()}, upsert=True)

    def registrar_trade(self, linha):
        self._post("robo_trades", {"modo": self.modo, **linha})

    def registrar_patrimonio(self, linha):
        self._post("robo_patrimonio", {"modo": self.modo, **linha})

    def handler_log(self):
        armazenamento = self

        class HandlerSupabase(logging.Handler):
            def emit(self, record):
                armazenamento._logs_pendentes.append({
                    "modo": armazenamento.modo, "nivel": record.levelname,
                    "mensagem": record.getMessage(),
                    "criado_em": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                })

        return HandlerSupabase()

    def descarregar(self):
        """Envia o log acumulado (uma requisição só)."""
        if not self._logs_pendentes:
            return
        pendentes, self._logs_pendentes = self._logs_pendentes, []
        try:
            self._post("robo_log", pendentes)
        except Exception as e:
            print(f"Falha ao enviar log ao Supabase: {e}")
