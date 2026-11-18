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
try:
    ex.load_markets()
    m = ex.market(cfg["par"])
    saldo = ex.fetch_balance()
    preco = ex.fetch_ticker(cfg["par"])["last"]
except ccxt.AuthenticationError as e:
    sys.exit(f"FALHOU: a corretora recusou a chave (confira chave/segredo e permissões). Detalhe: {e}")
except Exception as e:
    sys.exit(f"FALHOU: {type(e).__name__}: {e}")

livre = saldo.get("free", {})
print("CONEXÃO OK com", cfg["exchange"])
print(f"Par {cfg['par']} | preço atual {preco}")
print(f"Saldo livre: {m['quote']} {livre.get(m['quote'], 0)} | {m['base']} {livre.get(m['base'], 0)}")
print(f"Ordem mínima: quantidade {m['limits']['amount']['min']} {m['base']} | valor {m['limits']['cost']['min']} {m['quote']}")
print("Nenhuma ordem foi enviada.")
