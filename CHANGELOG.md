# Changelog

## [0.1.0] - não publicada

### Adicionado
- Cliente `Sicredi` com configuração explícita por instância (sem estado global).
- Certificado mTLS em PFX/P12 ou par PEM, validado na construção do cliente.
- OAuth2 `client_credentials` com cache por credencial e escopo e `TokenStore` plugável.
- API de Extrato de Conta Corrente com paginação automática, deduplicação por
  `idMovimento` e detecção de extrato incompleto.
- API de Saldo de Conta Corrente.
- Modelos tipados (`Extrato`, `Movimento`, `PaginaExtrato`, `Saldo`) com `Decimal`.
- Hierarquia de exceções a partir de `SicrediError`.
