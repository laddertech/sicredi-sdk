"""Modelos tipados das respostas da API.

Valores monetários são ``Decimal`` e datas são ``date``. Cada modelo guarda o
JSON original em ``dados``, para campos que a API venha a acrescentar antes de
o SDK modelá-los.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sicredi.exceptions import RespostaInvalidaError


def _decimal(valor: Any, campo: str, *, obrigatorio: bool = True) -> Decimal | None:
    if valor is None or valor == '':
        if obrigatorio:
            raise RespostaInvalidaError(f'Campo {campo!r} ausente na resposta.')
        return None
    if isinstance(valor, bool):
        raise RespostaInvalidaError(f'Campo {campo!r} com valor inválido: {valor!r}')
    try:
        numero = valor if isinstance(valor, Decimal) else Decimal(str(valor))
    except InvalidOperation:
        numero = None
    if numero is None or not numero.is_finite():
        raise RespostaInvalidaError(f'Campo {campo!r} com valor inválido: {valor!r}')
    return numero


def _data(valor: Any, campo: str) -> date:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str):
        texto = valor.strip()
        try:
            if len(texto) >= 10 and texto[4] == '-':
                return date.fromisoformat(texto[:10])
            if len(texto) == 10 and texto[2] == '/':
                return datetime.strptime(texto, '%d/%m/%Y').date()
        except ValueError:
            pass
    raise RespostaInvalidaError(f'Campo {campo!r} com data inválida: {valor!r}')


def _texto(valor: Any) -> str | None:
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


@dataclass(frozen=True)
class Movimento:
    """Lançamento do extrato.

    ``id_movimento`` é o identificador do Sicredi e serve de chave de
    deduplicação em importações repetidas.
    """

    data: date
    descricao: str | None
    valor: Decimal
    saldo: Decimal | None
    complemento: str | None = None
    documento: str | None = None
    codigo_lancamento: str | None = None
    id_movimento: str | None = None
    dados: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def credito(self) -> bool:
        return self.valor > 0

    @property
    def debito(self) -> bool:
        return self.valor < 0

    @classmethod
    def from_api(cls, dados: dict[str, Any]) -> Movimento:
        if not isinstance(dados, dict):
            raise RespostaInvalidaError('Movimento do extrato não é um objeto.')
        return cls(
            data=_data(dados.get('data'), 'data'),
            descricao=_texto(dados.get('descricao')),
            valor=_decimal(dados.get('valor'), 'valor'),  # type: ignore[arg-type]
            saldo=_decimal(dados.get('saldo'), 'saldo', obrigatorio=False),
            complemento=_texto(dados.get('complemento')),
            documento=_texto(dados.get('documento')),
            codigo_lancamento=_texto(dados.get('codigoLancamento')),
            id_movimento=_texto(dados.get('idMovimento')),
            dados=dados,
        )


@dataclass(frozen=True)
class PaginaExtrato:
    """Uma página da consulta de extrato, como devolvida pela API."""

    saldo_anterior: Decimal
    movimentos: list[Movimento]
    pagina: int
    total_paginas: int
    total_movimentos: int
    tamanho_pagina: int | None
    dados: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, dados: dict[str, Any]) -> PaginaExtrato:
        brutos = dados.get('dtlMovimentos')
        if brutos is None:
            brutos = []
        if not isinstance(brutos, list):
            raise RespostaInvalidaError("Campo 'dtlMovimentos' não é uma lista.")
        movimentos = [Movimento.from_api(item) for item in brutos]
        return cls(
            saldo_anterior=_decimal(dados.get('saldoAnterior'), 'saldoAnterior'),  # type: ignore[arg-type]
            movimentos=movimentos,
            # Sem os metadados não há como saber se o extrato está completo:
            # exigi-los evita tratar uma resposta truncada como o período todo.
            pagina=_inteiro(dados.get('pageNumber'), 'pageNumber'),  # type: ignore[arg-type]
            total_paginas=_inteiro(dados.get('totalPages'), 'totalPages'),  # type: ignore[arg-type]
            total_movimentos=_inteiro(dados.get('totalElements'), 'totalElements'),  # type: ignore[arg-type]
            tamanho_pagina=_inteiro(
                dados.get('pageSize'), 'pageSize', obrigatorio=False
            )
            or None,
            dados=dados,
        )


def _inteiro(valor: Any, campo: str, *, obrigatorio: bool = True) -> int | None:
    if valor is None or valor == '':
        if obrigatorio:
            raise RespostaInvalidaError(f'Campo {campo!r} ausente na resposta.')
        return None
    if isinstance(valor, bool):
        raise RespostaInvalidaError(f'Campo {campo!r} com valor inválido: {valor!r}')
    try:
        numero = Decimal(str(valor))
    except InvalidOperation:
        raise RespostaInvalidaError(
            f'Campo {campo!r} com valor inválido: {valor!r}'
        ) from None
    if not numero.is_finite() or numero != numero.to_integral_value() or numero < 0:
        raise RespostaInvalidaError(f'Campo {campo!r} com valor inválido: {valor!r}')
    return int(numero)


@dataclass(frozen=True)
class Extrato:
    """Extrato completo do período (todas as páginas reunidas)."""

    data_inicio: date
    data_fim: date
    saldo_anterior: Decimal
    movimentos: list[Movimento]

    @property
    def saldo_final(self) -> Decimal:
        """Saldo após o último movimento.

        Parte do último saldo informado pela API (ou do saldo anterior, se
        nenhum movimento traz saldo) e soma os valores posteriores a ele.
        """
        base = self.saldo_anterior
        inicio = 0
        for indice in range(len(self.movimentos) - 1, -1, -1):
            saldo = self.movimentos[indice].saldo
            if saldo is not None:
                base, inicio = saldo, indice + 1
                break
        return base + sum((m.valor for m in self.movimentos[inicio:]), Decimal('0'))

    @property
    def total_creditos(self) -> Decimal:
        return sum((m.valor for m in self.movimentos if m.valor > 0), Decimal('0'))

    @property
    def total_debitos(self) -> Decimal:
        return sum((m.valor for m in self.movimentos if m.valor < 0), Decimal('0'))


_CAMPOS_SALDO = {
    'saldo_atual': 'saldoAtual',
    'saldo_conta_corrente': 'saldoContaCorrente',
    'saldo_aplicacao_automatica': 'saldoAplicAutomatica',
    'saldo_bloqueado_cheques': 'saldoBloqueadoParaCheques',
    'saldo_lancamentos_a_conferir': 'saldoLancamentosAConferir',
    'saldo_bloqueio_judicial': 'saldoBloqueioJudicial',
    'saldo_retido': 'saldoRetido',
    'limite_cheque_especial': 'limiteChequeEspecial',
    'limite_cheque_especial_utilizado': 'limiteChequeEspecialUtilizado',
    'limite_cheque_especial_disponivel': 'limiteChequeEspecialDisponivel',
}


@dataclass(frozen=True)
class Saldo:
    """Saldo da conta vinculada à credencial."""

    saldo_atual: Decimal
    saldo_conta_corrente: Decimal | None
    saldo_aplicacao_automatica: Decimal | None
    saldo_bloqueado_cheques: Decimal | None
    saldo_lancamentos_a_conferir: Decimal | None
    saldo_bloqueio_judicial: Decimal | None
    saldo_retido: Decimal | None
    limite_cheque_especial: Decimal | None
    limite_cheque_especial_utilizado: Decimal | None
    limite_cheque_especial_disponivel: Decimal | None
    dados: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, dados: dict[str, Any]) -> Saldo:
        valores = {
            atributo: _decimal(dados.get(chave), chave, obrigatorio=False)
            for atributo, chave in _CAMPOS_SALDO.items()
        }
        if valores['saldo_atual'] is None:
            raise RespostaInvalidaError(
                "Resposta de saldo sem 'saldoAtual'.", body=dados
            )
        return cls(**valores, dados=dados)
