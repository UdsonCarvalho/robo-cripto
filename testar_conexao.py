"""Testa a conexão com a corretora SEM enviar nenhuma ordem.

Lê o saldo e as regras do par (mínimo de ordem, precisão). Use antes de ligar o modo real.
Uso:  py -3.13 testar_conexao.py   (ou pelo GitHub: Actions -> "Testar conexao")
"""
import os
import sys

import ccxt
from dotenv import load_dotenv

from configuracao import PASTA, carregar_config

load_dotenv(os.path.join(PASTA, ".env"))
cfg = carregar_config()
chave, segredo = os.getenv("API_KEY"), os.getenv("API_SECRET")
if not chave or not segredo:
    sys.exit("FALHOU: faltam API_KEY e API_SECRET (no .env ou nos Secrets do GitHub).")

ex = getattr(ccxt, cfg["exchange"])({"apiKey": chave, "secret": segredo, "enableRateLimit": True})
pares = [p["par"] for p in (cfg.get("pares") or [{"par": cfg["par"]}])]
try:
    ex.load_markets()
    faltando = [p for p in pares if p not in ex.markets]
    if faltando:
        sys.exit(f"FALHOU: a {cfg['exchange']} não tem o(s) mercado(s): {', '.join(faltando)}")
    m = ex.market(pares[0])
    saldo = ex.fetch_balance()
    precos = {p: ex.fetch_ticker(p)["last"] for p in pares}
except ccxt.AuthenticationError as e:
    sys.exit(f"FALHOU: a corretora recusou a chave (confira chave/segredo e permissões). Detalhe: {e}")
except Exception as e:
    sys.exit(f"FALHOU: {type(e).__name__}: {e}")

livre = saldo.get("free", {})
print("CONEXÃO OK com", cfg["exchange"])
for p, preco in precos.items():
    mm = ex.market(p)
    print(f"Par {p} | preço atual {preco} | ordem mínima {mm['limits']['amount']['min']} {mm['base']}")
print("Saldo livre: " + " | ".join(f"{moeda} {livre.get(moeda, 0)}" for moeda in
      [m["quote"]] + [ex.market(p)["base"] for p in pares]))
print("Nenhuma ordem foi enviada.")
