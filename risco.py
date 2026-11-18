"""Gestão de risco — usada igualzinho no backtest e no bot."""


def tamanho_posicao(capital, preco_entrada, preco_stop, cfg_risco):
    """Quantidade de moeda a comprar.

    Duas travas, vale a menor:
      1. se o stop for atingido, a perda é no máximo `risco_por_trade` do capital;
      2. a posição nunca passa de `exposicao_maxima` do capital.
    """
    distancia = preco_entrada - preco_stop
    if distancia <= 0 or capital <= 0 or preco_entrada <= 0:
        return 0.0
    qtd_pelo_risco = capital * cfg_risco["risco_por_trade"] / distancia
    qtd_maxima = capital * cfg_risco["exposicao_maxima"] / preco_entrada
    return min(qtd_pelo_risco, qtd_maxima)


def pode_operar_hoje(pnl_dia, capital_inicio_dia, trades_dia, cfg_risco):
    if trades_dia >= cfg_risco["max_trades_dia"]:
        return False, "limite de trades do dia atingido"
    limite = cfg_risco["perda_diaria_maxima"] * capital_inicio_dia
    if capital_inicio_dia > 0 and pnl_dia <= -limite:
        return False, "limite de perda diária atingido"
    return True, ""


def aplicar_teto_capital(capital, cfg_risco):
    teto = cfg_risco.get("capital_maximo") or 0
    return min(capital, teto) if teto > 0 else capital


def limites_do_dia_em_reais(pnl_total_dia, cfg_risco):
    """Perda/meta do dia em dinheiro, somando todos os mercados (resultado realizado)."""
    perda = cfg_risco.get("perda_dia_reais") or 0
    meta = cfg_risco.get("meta_dia_reais") or 0
    if perda > 0 and pnl_total_dia <= -perda:
        return False, f"perda do dia de {pnl_total_dia:.2f} atingiu o limite de {perda:.2f}; volta amanhã"
    if meta > 0 and pnl_total_dia >= meta:
        return False, f"meta do dia batida ({pnl_total_dia:.2f} >= {meta:.2f}); volta amanhã"
    return True, ""
