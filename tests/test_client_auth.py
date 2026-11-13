from urllib.parse import parse_qs

import pytest
import responses

from sicredi import (
    Ambiente,
    ApiError,
    AutenticacaoError,
    ConfiguracaoError,
    MemoryTokenStore,
    RespostaInvalidaError,
    Sicredi,
)
from sicredi.auth import OAuth2Client, Token
from sicredi.config import Config

from .conftest import (
    EXTRATO_SB,
    PRODUCAO,
    SALDO_SB,
    TOKEN_SB,
    registrar_token,
)

SALDO = {'saldoAtual': 10.5}


def test_config_urls():
    assert Config(Ambiente.SANDBOX).token_url == TOKEN_SB
    assert Config(Ambiente.PRODUCAO).token_url == f'{PRODUCAO}/thirdparty/auth/token'
    assert (
        Config(Ambiente.PRODUCAO, base_url='https://proxy/x/').url('/a/b')
        == 'https://proxy/x/a/b'
    )


@pytest.mark.parametrize(
    ('valor', 'esperado'),
    [
        ('sandbox', Ambiente.SANDBOX),
        (' PROD ', Ambiente.PRODUCAO),
        ('producao', Ambiente.PRODUCAO),
        (Ambiente.SANDBOX, Ambiente.SANDBOX),
    ],
)
def test_ambiente_parse(valor, esperado):
    assert Ambiente.parse(valor) is esperado


def test_ambiente_desconhecido():
    with pytest.raises(ConfiguracaoError):
        Ambiente.parse('qa')


@pytest.mark.parametrize(
    ('client_id', 'client_secret', 'extra'),
    [('', 's', {}), ('id', ' ', {}), ('id', 's', {'timeout': 0})],
)
def test_cliente_valida_configuracao(pfx, client_id, client_secret, extra):
    with pytest.raises(ConfiguracaoError):
        Sicredi(
            client_id,
            client_secret,
            ambiente='sandbox',
            certificado_pfx=pfx,
            senha_pfx='senha-pfx',
            **extra,
        )


def test_ambiente_e_obrigatorio(pfx):
    with pytest.raises(TypeError):
        Sicredi('id', 's', certificado_pfx=pfx, senha_pfx='senha-pfx')  # type: ignore[call-arg]


def test_repr_nao_vaza_segredo(cliente):
    assert 'client-secret' not in repr(cliente)
    assert repr(cliente) == "Sicredi(ambiente='sandbox')"


def test_token_enviado_com_escopo_e_reaproveitado(cliente, mock_http):
    chamada_token = registrar_token(mock_http)
    mock_http.add(responses.GET, SALDO_SB, json=SALDO)

    cliente.conta_corrente.saldo()
    cliente.conta_corrente.saldo()

    assert chamada_token.call_count == 1
    corpo = parse_qs(mock_http.calls[0].request.body)
    assert corpo == {
        'grant_type': ['client_credentials'],
        'client_id': ['client-id'],
        'client_secret': ['client-secret'],
        'scope': ['contacorrente.saldo.consultar'],
    }
    assert mock_http.calls[1].request.headers['Authorization'] == 'Bearer tok-1'


def test_token_separado_por_escopo(cliente, mock_http):
    chamada_token = registrar_token(mock_http)
    mock_http.add(responses.GET, SALDO_SB, json=SALDO)
    mock_http.add(
        responses.GET,
        EXTRATO_SB,
        json={
            'saldoAnterior': 0,
            'dtlMovimentos': [],
            'totalPages': 1,
            'totalElements': 0,
            'pageNumber': 0,
        },
    )
    cliente.conta_corrente.saldo()
    cliente.conta_corrente.extrato('2026-11-01', '2026-11-02')
    assert chamada_token.call_count == 2


def test_renova_token_e_repete_uma_vez_apos_401(cliente, mock_http):
    mock_http.add(responses.POST, TOKEN_SB, json={'access_token': 'velho'})
    mock_http.add(responses.POST, TOKEN_SB, json={'access_token': 'novo'})
    mock_http.add(
        responses.GET, SALDO_SB, status=401, json={'detail': 'Token inválido'}
    )
    mock_http.add(responses.GET, SALDO_SB, json=SALDO)

    saldo = cliente.conta_corrente.saldo()

    assert str(saldo.saldo_atual) == '10.5'
    assert mock_http.calls[-1].request.headers['Authorization'] == 'Bearer novo'


def test_401_persistente_propaga(cliente, mock_http):
    registrar_token(mock_http)
    mock_http.add(
        responses.GET, SALDO_SB, status=401, json={'detail': 'Token inválido'}
    )
    with pytest.raises(AutenticacaoError, match='Token inválido'):
        cliente.conta_corrente.saldo()
    get_calls = [c for c in mock_http.calls if c.request.method == 'GET']
    assert len(get_calls) == 2


def test_falha_no_token(cliente, mock_http):
    mock_http.add(
        responses.POST,
        TOKEN_SB,
        status=401,
        json={'error': 'invalid_client', 'error_description': 'Credencial inválida'},
    )
    with pytest.raises(AutenticacaoError, match='Credencial inválida') as exc:
        cliente.conta_corrente.saldo()
    assert exc.value.status_code == 401


def test_token_sem_access_token(cliente, mock_http):
    mock_http.add(responses.POST, TOKEN_SB, json={'expires_in': 3600})
    with pytest.raises(RespostaInvalidaError, match='access_token'):
        cliente.conta_corrente.saldo()


class _TransporteFalso:
    def __init__(self):
        self.chamadas = 0

    def post_form(self, url, dados, *, contexto):
        self.chamadas += 1
        return {'access_token': f't{self.chamadas}', 'expires_in': 'x'}


def test_token_expira_e_renova_com_margem():
    agora = [1000.0]
    transporte = _TransporteFalso()
    oauth = OAuth2Client(transporte, 'id', 's', 'https://t', relogio=lambda: agora[0])
    assert oauth.token('e') == 't1'  # expires_in inválido → 3600 s
    agora[0] += 3600 - 61
    assert oauth.token('e') == 't1'
    agora[0] += 2  # entrou na margem de renovação
    assert oauth.token('e') == 't2'


def test_cache_compartilhado_isola_credenciais():
    store = MemoryTokenStore()
    a = OAuth2Client(_TransporteFalso(), 'conta-a', 's', 'https://t', store)
    b = OAuth2Client(_TransporteFalso(), 'conta-b', 's', 'https://t', store)
    c = OAuth2Client(_TransporteFalso(), 'conta-a', 'outro', 'https://t', store)
    a.token('e')
    assert b.token('e') == 't1'
    assert c.token('e') == 't1'
    assert len(store._dados) == 3
    assert all('conta' not in chave for chave in store._dados)


def test_token_store_customizado(pfx, mock_http):
    class Store(MemoryTokenStore):
        ttls = []

        def set(self, chave, token, ttl):
            self.ttls.append(ttl)
            super().set(chave, token, ttl)

    store = Store()
    registrar_token(mock_http, expires_in=600)
    mock_http.add(responses.GET, SALDO_SB, json=SALDO)
    with Sicredi(
        'id',
        's',
        ambiente='sandbox',
        certificado_pfx=pfx,
        senha_pfx='senha-pfx',
        token_store=store,
    ) as sicredi:
        sicredi.conta_corrente.saldo()
    assert 595 <= store.ttls[0] <= 600


def test_token_nao_expoe_segredo_no_repr():
    assert 'segredo' not in repr(Token('segredo', expira_em=1))


def test_token_valido():
    assert Token('x', expira_em=1000).valido(agora=900)
    assert not Token('x', expira_em=1000).valido(agora=950)


@pytest.mark.parametrize(
    'url', ['http://mtls-api-parceiro.sicredi.com.br', 'https://', 'ftp://x', '']
)
def test_base_url_exige_https(url):
    with pytest.raises(ConfiguracaoError, match='https'):
        Config(Ambiente.PRODUCAO, base_url=url)


def test_redirecionamento_recusado(cliente, mock_http):
    mock_http.add(
        responses.POST,
        TOKEN_SB,
        status=302,
        headers={'Location': 'http://outro-host/token'},
    )
    with pytest.raises(ApiError, match='redirecionamento recusado') as exc:
        cliente.conta_corrente.saldo()
    assert exc.value.status_code == 302
    assert len(mock_http.calls) == 1


def test_invalidar_nao_apaga_token_ja_renovado():
    transporte = _TransporteFalso()
    oauth = OAuth2Client(transporte, 'id', 's', 'https://t')
    velho = oauth.token('e')
    oauth.invalidar('e', velho)  # 1º 401: descarta o velho
    novo = oauth.token('e')
    oauth.invalidar('e', velho)  # 401 atrasado com o velho: não mexe no novo
    assert oauth.token('e') == novo
    assert transporte.chamadas == 2
    oauth.invalidar('e')  # sem token: descarta incondicionalmente
    assert oauth.token('e') == 't3'


def test_mtls_montado_so_na_origem_e_sessao_exclusiva(cliente, pfx):
    from requests_pkcs12 import Pkcs12Adapter

    from sicredi import Sicredi

    sessao = cliente._transporte.session
    origem = 'https://mtls-api-parceiro.sicredi.com.br/'
    assert isinstance(sessao.get_adapter(origem + 'sb/x'), Pkcs12Adapter)
    assert not isinstance(sessao.get_adapter('https://outro.com/'), Pkcs12Adapter)
    with Sicredi(
        'id', 's', ambiente='sandbox', certificado_pfx=pfx, senha_pfx='senha-pfx'
    ) as outro:
        assert outro._transporte.session is not sessao
        assert outro._transporte.session.adapters[origem] is not sessao.adapters[origem]


def test_origem_com_base_url():
    cfg = Config(Ambiente.PRODUCAO, base_url='https://proxy.local:8443/api/')
    assert cfg.origem == 'https://proxy.local:8443'


def test_cache_compartilhado_isola_certificados(pem_cert, pem_chave, mock_http):
    from cryptography.hazmat.primitives import serialization

    from .conftest import gerar_certificado

    chave2, cert2 = gerar_certificado()
    store = MemoryTokenStore()
    chamada_token = registrar_token(mock_http)
    mock_http.add(responses.GET, SALDO_SB, json=SALDO)
    certificados = [
        (pem_cert, pem_chave),
        (
            cert2.public_bytes(serialization.Encoding.PEM),
            chave2.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
        ),
    ]
    for cert, chave in certificados:
        with Sicredi(
            'id',
            's',
            ambiente='sandbox',
            certificado=cert,
            chave_privada=chave,
            token_store=store,
        ) as sicredi:
            sicredi.conta_corrente.saldo()
    assert chamada_token.call_count == 2


def test_netrc_nao_sobrescreve_bearer(cliente, mock_http, tmp_path, monkeypatch):
    netrc = tmp_path / '.netrc'
    netrc.write_text(
        'machine mtls-api-parceiro.sicredi.com.br login usuario password segredo\n'
    )
    netrc.chmod(0o600)
    monkeypatch.setenv('NETRC', str(netrc))
    registrar_token(mock_http)
    mock_http.add(responses.GET, SALDO_SB, json=SALDO)
    cliente.conta_corrente.saldo()
    assert 'Authorization' not in mock_http.calls[0].request.headers
    assert mock_http.calls[1].request.headers['Authorization'] == 'Bearer tok-1'
