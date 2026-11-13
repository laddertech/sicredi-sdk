# sicredi-sdk

SDK Python para as APIs de parceiros do **Sicredi**.

| API | Status |
|---|---|
| Extrato de Conta Corrente | ✅ v0.1 |
| Saldo de Conta Corrente | ✅ v0.1 |
| Cobrança (boleto) | planejada |
| Pix | use a [`pypix-api`](https://pypi.org/project/pypix-api/) (padrão Bacen) |

Documentação oficial: <https://developers.sicredi.com.br/public/docs/getting-started>

## Instalação

```bash
pip install sicredi-sdk
# ou
uv add sicredi-sdk
```

Requer Python 3.10+.

## Uso

```python
from datetime import date
from sicredi import Sicredi

with Sicredi(
    client_id='...',
    client_secret='...',
    certificado_pfx='certificado.pfx',  # caminho, bytes ou arquivo aberto
    senha_pfx='...',
    ambiente='sandbox',  # obrigatório: "sandbox" ou "producao"
) as sicredi:
    extrato = sicredi.conta_corrente.extrato(date(2026, 11, 1), date(2026, 11, 13))
    print(extrato.saldo_anterior, extrato.saldo_final)
    for mov in extrato.movimentos:
        print(mov.data, mov.descricao, mov.valor, mov.id_movimento)

    saldo = sicredi.conta_corrente.saldo()
    print(saldo.saldo_atual, saldo.limite_cheque_especial_disponivel)
```

### Certificado mTLS

As APIs de conta corrente exigem mTLS em todas as chamadas, inclusive na do
token. Informe o certificado de **uma** das formas:

```python
# PFX / P12
Sicredi(..., certificado_pfx=b'...bytes...', senha_pfx='senha')

# Par PEM, como o Portal do Desenvolvedor entrega
Sicredi(..., certificado='cert.pem', chave_privada='chave.key')
Sicredi(..., certificado=texto_pem, chave_privada=texto_pem, senha_chave='frase')
```

O certificado é validado na construção do cliente: senha errada, arquivo
ilegível ou certificado vencido levantam `CertificadoError` antes de qualquer
chamada à API.

### Extrato

- `extrato(data_inicio, data_fim, tamanho_pagina=None)` reúne todas as páginas
  e devolve um `Extrato`. Movimentos repetidos entre páginas (mesmo
  `id_movimento`) aparecem uma vez. Se faltarem movimentos em relação ao total
  informado pela API, o SDK levanta `RespostaInvalidaError` em vez de devolver
  um extrato incompleto (o extrato mudou durante a paginação; repita).
- `extrato_pagina(data_inicio, data_fim, pagina=0, tamanho_pagina=None)`
  devolve uma única página (`PaginaExtrato`). A primeira página é 0.
- Datas aceitam `date`, `datetime` ou texto `yyyy-mm-dd`.
- Valores são `Decimal`; datas são `date`. O JSON original fica em `.dados`.
- Contas do core legado do Sicredi podem ter movimentos com atraso D-1.

### Cache de tokens

Por padrão o token fica em memória do processo e é renovado 60 s antes de
expirar. Em aplicações com vários processos, implemente `TokenStore`:

```python
from sicredi import Token, TokenStore


class RedisTokenStore:
    def get(self, chave: str) -> Token | None: ...
    def set(self, chave: str, token: Token, ttl: int) -> None: ...
    def delete(self, chave: str) -> None: ...


Sicredi(..., token_store=RedisTokenStore())
```

A chave do cache é um hash de URL do token + `client_id` + `client_secret` +
impressão digital do certificado + escopo: contas diferentes nunca compartilham token, mesmo com um store comum.

Se a API devolver 401, o SDK descarta o token, obtém outro e repete a chamada
uma única vez.

### Erros

Todas as exceções descendem de `SicrediError`:

| Exceção | Quando |
|---|---|
| `ConfiguracaoError` / `CertificadoError` | configuração local inválida |
| `ValidacaoError` | parâmetro inválido, antes de chamar a API |
| `ConexaoError` | timeout, DNS, TLS |
| `RequisicaoInvalidaError` | HTTP 400/422 |
| `AutenticacaoError` | HTTP 401 / falha ao obter token |
| `PermissaoError` | HTTP 403 (escopo não liberado, conta inválida) |
| `LimiteRequisicoesError` | HTTP 429 |
| `ServidorError` | HTTP 5xx |
| `RespostaInvalidaError` | resposta fora do contrato |

`ApiError` (base das HTTP) expõe `status_code`, `detail` e `body`.

## Acesso às APIs (adesão)

1. Manifeste interesse à sua cooperativa e informe cooperativa, conta,
   CPF/CNPJ, e-mail para o Portal e as APIs desejadas (Extrato, Saldo).
2. Receba o ID de adesão por e-mail.
3. Cadastre-se no [Portal do Desenvolvedor](https://developer.sicredi.com.br)
   com o e-mail da adesão e abra um chamado informando o ID.
4. Aprovado, registre um CSR e baixe o certificado e a chave.
5. Teste no sandbox e peça as credenciais de produção.

Quem já usa Multipag ou uma das APIs de conta pode pedir só a inclusão do
escopo (`contacorrente.extratos.consultar`, `contacorrente.saldo.consultar`).

## Desenvolvimento

```bash
make install   # uv sync
make test
make cov
make lint
```

## Licença

MIT
