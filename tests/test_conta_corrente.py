from datetime import date, datetime
from decimal import Decimal

import pytest
import requests
import responses
from responses import matchers

from sicredi import (
    ApiError,
    ConexaoError,
    LimiteRequisicoesError,
    PermissaoError,
    RequisicaoInvalidaError,
    RespostaInvalidaError,
    ServidorError,
    ValidacaoError,
)
from sicredi.conta_corrente import LIMITE_PAGINAS

from .conftest import EXTRATO_SB, SALDO_SB, registrar_token

# Exemplo da documentação oficial.
EXEMPLO_DOC = {
    'saldoAnterior': -500.0,
    'dtlMovimentos': [
        {
            'data': '2026-02-02',
            'descricao': 'CHEQUE ESPECIAL INAD-IOF',
            'complemento': None,
            'documento': None,
            'valor': -1.27,
            'saldo': -501.27,
            'codigoLancamento': '262',
            'idMovimento': '20260202-3500410-1-1',
        }
    ],
    'quantidade': 1,
    'totalElements': 1,
    'totalPages': 1,
    'pageNumber': 0,
    'pageSize': 30,
}


def mov(i, valor='1.00', saldo=None):
    return {
        'data': '2026-11-01',
        'descricao': f'MOV {i}',
        'valor': valor,
        'saldo': saldo,
        'idMovimento': f'id-{i}',
    }


def pagina(numero, movimentos, total_paginas, total, saldo_anterior=100):
    return {
        'saldoAnterior': saldo_anterior,
        'dtlMovimentos': movimentos,
        'totalElements': total,
        'totalPages': total_paginas,
        'pageNumber': numero,
        'pageSize': 2,
    }


def add_pagina(rsps, numero, corpo, size=None):
    params = {'dataInicio': '2026-11-01', 'dataFim': '2026-11-30', 'page': str(numero)}
    if size is not None:
        params['size'] = str(size)
    rsps.add(
        responses.GET,
        EXTRATO_SB,
        json=corpo,
        match=[matchers.query_param_matcher(params)],
    )


def test_extrato_exemplo_da_documentacao(cliente, mock_http):
    registrar_token(mock_http)
    mock_http.add(
        responses.GET,
        EXTRATO_SB,
        json=EXEMPLO_DOC,
        match=[
            matchers.query_param_matcher(
                {'dataInicio': '2026-05-20', 'dataFim': '2026-06-30', 'page': '0'}
            )
        ],
    )
    extrato = cliente.conta_corrente.extrato(date(2026, 5, 20), date(2026, 6, 30))

    assert extrato.saldo_anterior == Decimal('-500.0')
    assert len(extrato.movimentos) == 1
    m = extrato.movimentos[0]
    assert m.data == date(2026, 2, 2)
    assert m.valor == Decimal('-1.27')
    assert isinstance(m.valor, Decimal)
    assert m.saldo == Decimal('-501.27')
    assert m.codigo_lancamento == '262'
    assert m.id_movimento == '20260202-3500410-1-1'
    assert m.complemento is None and m.documento is None
    assert m.debito and not m.credito
    assert m.dados['descricao'] == 'CHEQUE ESPECIAL INAD-IOF'
    assert extrato.saldo_final == Decimal('-501.27')
    assert extrato.total_debitos == Decimal('-1.27')
    assert extrato.total_creditos == Decimal('0')


def test_extrato_reune_paginas(cliente, mock_http):
    registrar_token(mock_http)
    add_pagina(mock_http, 0, pagina(0, [mov(1), mov(2)], 3, 5), size=2)
    add_pagina(mock_http, 1, pagina(1, [mov(3), mov(4)], 3, 5), size=2)
    add_pagina(mock_http, 2, pagina(2, [mov(5, '-2.50')], 3, 5), size=2)

    extrato = cliente.conta_corrente.extrato('2026-11-01', '2026-11-30', 2)

    assert [m.id_movimento for m in extrato.movimentos] == [
        f'id-{i}' for i in range(1, 6)
    ]
    assert extrato.saldo_anterior == Decimal('100')
    # sem saldo por movimento: soma a partir do anterior
    assert extrato.saldo_final == Decimal('101.50')


def test_extrato_deduplica_movimento_repetido_entre_paginas(cliente, mock_http):
    registrar_token(mock_http)
    add_pagina(mock_http, 0, pagina(0, [mov(1), mov(2)], 2, 3))
    add_pagina(mock_http, 1, pagina(1, [mov(2), mov(3)], 2, 3))
    extrato = cliente.conta_corrente.extrato('2026-11-01', '2026-11-30')
    assert [m.id_movimento for m in extrato.movimentos] == ['id-1', 'id-2', 'id-3']


def test_extrato_incompleto_levanta(cliente, mock_http):
    registrar_token(mock_http)
    # um movimento novo deslocou a página 1: id-2 repetiu e um ficou de fora
    add_pagina(mock_http, 0, pagina(0, [mov(1), mov(2)], 2, 4))
    add_pagina(mock_http, 1, pagina(1, [mov(2), mov(3)], 2, 4))
    with pytest.raises(RespostaInvalidaError, match='incompleto: 3 de 4'):
        cliente.conta_corrente.extrato('2026-11-01', '2026-11-30')


def test_extrato_pagina_ignorada_pelo_servidor(cliente, mock_http):
    registrar_token(mock_http)
    add_pagina(mock_http, 0, pagina(0, [mov(1)], 2, 2))
    add_pagina(mock_http, 1, pagina(0, [mov(1)], 2, 2))
    with pytest.raises(RespostaInvalidaError, match='Pedida a página 1'):
        cliente.conta_corrente.extrato('2026-11-01', '2026-11-30')


def test_extrato_primeira_pagina_errada(cliente, mock_http):
    registrar_token(mock_http)
    add_pagina(mock_http, 0, pagina(1, [mov(1)], 1, 1))
    with pytest.raises(RespostaInvalidaError, match='Primeira página'):
        cliente.conta_corrente.extrato('2026-11-01', '2026-11-30')


def test_extrato_limite_de_paginas(cliente, mock_http):
    registrar_token(mock_http)
    add_pagina(mock_http, 0, pagina(0, [mov(1)], LIMITE_PAGINAS + 1, 1))
    with pytest.raises(RespostaInvalidaError, match='excede o limite'):
        cliente.conta_corrente.extrato('2026-11-01', '2026-11-30')


def test_extrato_vazio(cliente, mock_http):
    registrar_token(mock_http)
    add_pagina(
        mock_http,
        0,
        {
            'saldoAnterior': '12.34',
            'dtlMovimentos': None,
            'totalPages': 0,
            'totalElements': 0,
            'pageNumber': 0,
        },
    )
    extrato = cliente.conta_corrente.extrato('2026-11-01', '2026-11-30')
    assert extrato.movimentos == []
    assert extrato.saldo_final == Decimal('12.34')


@pytest.mark.parametrize('campo', ['totalPages', 'totalElements', 'pageNumber'])
def test_extrato_sem_metadados_de_paginacao(cliente, mock_http, campo):
    registrar_token(mock_http)
    corpo = pagina(0, [mov(1)], 1, 1)
    del corpo[campo]
    add_pagina(mock_http, 0, corpo)
    with pytest.raises(RespostaInvalidaError, match=f"'{campo}' ausente"):
        cliente.conta_corrente.extrato('2026-11-01', '2026-11-30')


def test_saldo_final_com_saldos_parcialmente_ausentes(cliente, mock_http):
    registrar_token(mock_http)
    add_pagina(
        mock_http,
        0,
        pagina(0, [mov(1, '10', '110'), mov(2, '5', None), mov(3, '-2', None)], 1, 3),
    )
    extrato = cliente.conta_corrente.extrato('2026-11-01', '2026-11-30')
    assert extrato.saldo_final == Decimal('113')


def test_extrato_pagina_unica(cliente, mock_http):
    registrar_token(mock_http)
    add_pagina(mock_http, 3, pagina(3, [mov(7)], 5, 9), size=2)
    pag = cliente.conta_corrente.extrato_pagina('2026-11-01', '2026-11-30', 3, 2)
    assert pag.pagina == 3
    assert pag.total_paginas == 5
    assert pag.total_movimentos == 9
    assert pag.tamanho_pagina == 2
    assert pag.movimentos[0].id_movimento == 'id-7'


@pytest.mark.parametrize(
    ('inicio', 'fim', 'kwargs'),
    [
        ('2026-11-30', '2026-11-01', {}),
        ('30/11/2026', '2026-12-01', {}),
        (20261101, '2026-12-01', {}),
        ('2026-11-01', '2026-11-30', {'pagina': -1}),
        ('2026-11-01', '2026-11-30', {'pagina': True}),
        ('2026-11-01', '2026-11-30', {'tamanho_pagina': 0}),
    ],
)
def test_extrato_valida_parametros(cliente, mock_http, inicio, fim, kwargs):
    with pytest.raises(ValidacaoError):
        cliente.conta_corrente.extrato_pagina(inicio, fim, **kwargs)
    assert len(mock_http.calls) == 0


def test_extrato_aceita_datetime(cliente, mock_http):
    registrar_token(mock_http)
    add_pagina(mock_http, 0, pagina(0, [], 1, 0))
    extrato = cliente.conta_corrente.extrato(
        datetime(2026, 11, 1, 15, 30), datetime(2026, 11, 30, 8)
    )
    assert extrato.data_inicio == date(2026, 11, 1)


@pytest.mark.parametrize(
    ('movimento', 'mensagem'),
    [
        ({'data': '2026-11-01'}, "'valor' ausente"),
        ({'data': '01-11-2026', 'valor': 1}, 'data inválida'),
        ({'data': '2026-11-01', 'valor': 'abc'}, 'valor inválido'),
        ({'data': '2026-11-01', 'valor': True}, 'valor inválido'),
        ({'data': '2026-11-01', 'valor': 'NaN'}, 'valor inválido'),
        ({'data': '2026-11-01', 'valor': '-Infinity'}, 'valor inválido'),
        ('texto', 'não é um objeto'),
    ],
)
def test_movimento_fora_do_contrato(cliente, mock_http, movimento, mensagem):
    registrar_token(mock_http)
    add_pagina(mock_http, 0, pagina(0, [movimento], 1, 1))
    with pytest.raises(RespostaInvalidaError, match=mensagem):
        cliente.conta_corrente.extrato('2026-11-01', '2026-11-30')


def test_movimento_formatos_alternativos_de_data(cliente, mock_http):
    registrar_token(mock_http)
    add_pagina(
        mock_http,
        0,
        pagina(
            0,
            [
                {'data': '2026-11-01T10:00:00', 'valor': 1, 'idMovimento': 'a'},
                {'data': '02/11/2026', 'valor': 1, 'idMovimento': 'b'},
            ],
            1,
            2,
        ),
    )
    extrato = cliente.conta_corrente.extrato('2026-11-01', '2026-11-30')
    assert [m.data for m in extrato.movimentos] == [
        date(2026, 11, 1),
        date(2026, 11, 2),
    ]


@pytest.mark.parametrize(
    'alteracao',
    [
        {'saldoAnterior': None},
        {'saldoAnterior': 'NaN'},
        {'dtlMovimentos': {}},
        {'totalPages': 'x'},
        {'totalPages': 1.5},
        {'totalPages': -1},
        {'totalPages': 'Infinity'},
        {'pageNumber': False},
    ],
)
def test_pagina_fora_do_contrato(cliente, mock_http, alteracao):
    registrar_token(mock_http)
    corpo = {**pagina(0, [mov(1)], 1, 1), **alteracao}
    add_pagina(mock_http, 0, corpo)
    with pytest.raises(RespostaInvalidaError):
        cliente.conta_corrente.extrato('2026-11-01', '2026-11-30')


def test_resposta_que_nao_e_objeto(cliente, mock_http):
    registrar_token(mock_http)
    mock_http.add(responses.GET, SALDO_SB, json=[1, 2])
    with pytest.raises(RespostaInvalidaError, match='JSON objeto'):
        cliente.conta_corrente.saldo()


def test_saldo(cliente, mock_http):
    registrar_token(mock_http)
    mock_http.add(
        responses.GET,
        SALDO_SB,
        json={
            'saldoAtual': 1500.75,
            'saldoContaCorrente': 1000.25,
            'saldoAplicAutomatica': 500.5,
            'saldoBloqueadoParaCheques': 0,
            'saldoLancamentosAConferir': 0,
            'saldoBloqueioJudicial': 0,
            'saldoRetido': 0,
            'limiteChequeEspecial': 2000,
            'limiteChequeEspecialUtilizado': 0,
            'limiteChequeEspecialDisponivel': 2000,
            'campoNovo': 'x',
        },
    )
    saldo = cliente.conta_corrente.saldo()
    assert saldo.saldo_atual == Decimal('1500.75')
    assert saldo.saldo_aplicacao_automatica == Decimal('500.5')
    assert saldo.limite_cheque_especial_disponivel == Decimal('2000')
    assert saldo.dados['campoNovo'] == 'x'
    assert mock_http.calls[-1].request.params == {}


@pytest.mark.parametrize(
    'corpo', [{'outro': 1}, {'limiteChequeEspecial': 2000, 'saldoAtual': None}]
)
def test_saldo_sem_saldo_atual(cliente, mock_http, corpo):
    registrar_token(mock_http)
    mock_http.add(responses.GET, SALDO_SB, json=corpo)
    with pytest.raises(RespostaInvalidaError, match='saldoAtual'):
        cliente.conta_corrente.saldo()


@pytest.mark.parametrize(
    ('status', 'classe'),
    [
        (400, RequisicaoInvalidaError),
        (403, PermissaoError),
        (429, LimiteRequisicoesError),
        (500, ServidorError),
        (503, ServidorError),
        (418, ApiError),
    ],
)
def test_erros_http(cliente, mock_http, status, classe):
    registrar_token(mock_http)
    mock_http.add(
        responses.GET,
        SALDO_SB,
        status=status,
        json={'detail': 'Privilégios insuficientes'},
    )
    with pytest.raises(classe, match='Privilégios insuficientes') as exc:
        cliente.conta_corrente.saldo()
    assert exc.value.status_code == status
    assert exc.value.detail == 'Privilégios insuficientes'
    assert exc.value.body == {'detail': 'Privilégios insuficientes'}


def test_erro_com_corpo_texto(cliente, mock_http):
    registrar_token(mock_http)
    mock_http.add(responses.GET, SALDO_SB, status=502, body='Bad Gateway')
    with pytest.raises(ServidorError, match='Bad Gateway'):
        cliente.conta_corrente.saldo()


def test_erro_sem_corpo(cliente, mock_http):
    registrar_token(mock_http)
    mock_http.add(responses.GET, SALDO_SB, status=500)
    with pytest.raises(ServidorError) as exc:
        cliente.conta_corrente.saldo()
    assert exc.value.detail is None


@pytest.mark.parametrize(
    ('falha', 'mensagem'),
    [
        (requests.ConnectTimeout('lento'), 'Tempo esgotado'),
        (requests.ConnectionError('dns'), 'Falha de conexão'),
    ],
)
def test_falhas_de_rede(cliente, mock_http, falha, mensagem):
    registrar_token(mock_http)
    mock_http.add(responses.GET, SALDO_SB, body=falha)
    with pytest.raises(ConexaoError, match=mensagem):
        cliente.conta_corrente.saldo()


def test_timeout_e_aplicado(pfx, mock_http):
    from sicredi import Sicredi

    registrar_token(mock_http)
    mock_http.add(responses.GET, SALDO_SB, json={'saldoAtual': 1})
    with Sicredi(
        'id',
        's',
        ambiente='sandbox',
        certificado_pfx=pfx,
        senha_pfx='senha-pfx',
        timeout=7,
    ) as sicredi:
        sicredi.conta_corrente.saldo()
    assert all(c.request.req_kwargs['timeout'] == 7 for c in mock_http.calls)


def test_producao_usa_host_sem_prefixo_sandbox(pfx, mock_http):
    from sicredi import Sicredi

    from .conftest import PRODUCAO

    registrar_token(mock_http, url=f'{PRODUCAO}/thirdparty/auth/token')
    mock_http.add(
        responses.GET, f'{PRODUCAO}/contacorrente/v1/saldos', json={'saldoAtual': 1}
    )
    with Sicredi(
        'id', 's', ambiente='producao', certificado_pfx=pfx, senha_pfx='senha-pfx'
    ) as sicredi:
        assert sicredi.conta_corrente.saldo().saldo_atual == Decimal('1')


def test_extrato_paginado_exige_id_movimento(cliente, mock_http):
    registrar_token(mock_http)
    sem_id = {'data': '2026-11-01', 'valor': '1'}
    add_pagina(mock_http, 0, pagina(0, [mov(1), sem_id], 2, 3))
    with pytest.raises(RespostaInvalidaError, match='sem idMovimento'):
        cliente.conta_corrente.extrato('2026-11-01', '2026-11-30')


def test_extrato_pagina_unica_aceita_movimento_sem_id(cliente, mock_http):
    registrar_token(mock_http)
    sem_id = {'data': '2026-11-01', 'valor': '1'}
    add_pagina(mock_http, 0, pagina(0, [sem_id, sem_id], 1, 2))
    extrato = cliente.conta_corrente.extrato('2026-11-01', '2026-11-30')
    assert len(extrato.movimentos) == 2


def test_extrato_saldo_anterior_mudou_entre_paginas(cliente, mock_http):
    registrar_token(mock_http)
    add_pagina(mock_http, 0, pagina(0, [mov(1)], 2, 2, saldo_anterior=100))
    add_pagina(mock_http, 1, pagina(1, [mov(2)], 2, 2, saldo_anterior=90))
    with pytest.raises(RespostaInvalidaError, match='saldo anterior mudou'):
        cliente.conta_corrente.extrato('2026-11-01', '2026-11-30')
