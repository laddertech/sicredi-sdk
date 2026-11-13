# CLAUDE.md

SDK Python das APIs de parceiros do Sicredi. Irmão do `sicoob-sdk`, mas sem
estado global: toda configuração é por instância do cliente `Sicredi`.

## Comandos

```bash
make install   # uv sync
make test      # uv run pytest -q
make cov       # cobertura (mínimo 90%)
make lint      # ruff check + ruff format --check
make format
```

## Arquitetura

- `sicredi/client.py` — `Sicredi`: valida config, carrega certificado, monta transporte e APIs.
- `sicredi/config.py` — `Ambiente` e `Config` (URLs; sandbox = prefixo `/sb`).
- `sicredi/certificado.py` — PFX ou PEM → `Identidade` (PKCS#12 em memória).
- `sicredi/_http.py` — `Transporte`: sessão `requests` + `Pkcs12Adapter`, erros HTTP → exceções.
- `sicredi/auth.py` — `OAuth2Client` (client_credentials) + `TokenStore`.
- `sicredi/conta_corrente.py` — extrato (paginado) e saldo.
- `sicredi/models.py` — dataclasses com `Decimal`/`date`; JSON original em `.dados`.

## Regras

- Dinheiro é sempre `Decimal` (JSON decodificado com `parse_float=Decimal`).
- Nada de variáveis de ambiente, `load_dotenv` ou singletons.
- A chave do cache de token inclui o secret (hash): nunca servir token de uma credencial a outra.
- Nunca logar `client_secret`, token ou certificado.
- Testes sem rede: `responses` para HTTP e certificados autoassinados gerados no `conftest`.
- Cada família de API do Sicredi tem autenticação própria (Cobrança não usa mTLS):
  ao adicionar uma, não presuma o fluxo das outras — confira a documentação oficial.
