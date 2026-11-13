"""APIs de Extrato e Saldo de Conta Corrente.

Ambas consultam a conta vinculada à credencial (não há parâmetro de
cooperativa/conta): o vínculo vem da adesão feita no Portal do Desenvolvedor.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sicredi.exceptions import (
    AutenticacaoError,
    RespostaInvalidaError,
    ValidacaoError,
)
from sicredi.models import Extrato, Movimento, PaginaExtrato, Saldo

if TYPE_CHECKING:
    from sicredi._http import Transporte
    from sicredi.auth import OAuth2Client
    from sicredi.config import Config

ESCOPO_EXTRATO = 'contacorrente.extratos.consultar'
ESCOPO_SALDO = 'contacorrente.saldo.consultar'

ROTA_EXTRATO = 'contacorrente/v1/extratos'
ROTA_SALDO = 'contacorrente/v1/saldos'

# Teto de segurança da paginação automática: evita laço sem fim se a API
# passar a devolver totalPages incoerente.
LIMITE_PAGINAS = 1000


def _como_data(valor: date | str, nome: str) -> date:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str):
        try:
            return date.fromisoformat(valor.strip())
        except ValueError:
            pass
    raise ValidacaoError(f'{nome} deve ser date ou texto yyyy-mm-dd: {valor!r}')


def _validar_periodo(
    data_inicio: date | str, data_fim: date | str
) -> tuple[date, date]:
    inicio = _como_data(data_inicio, 'data_inicio')
    fim = _como_data(data_fim, 'data_fim')
    if inicio > fim:
        raise ValidacaoError('data_inicio não pode ser posterior a data_fim.')
    return inicio, fim


def _validar_inteiro(valor: Any, nome: str, minimo: int) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < minimo:
        raise ValidacaoError(f'{nome} deve ser inteiro >= {minimo}: {valor!r}')
    return valor


class ContaCorrenteAPI:
    """Extrato e saldo da conta corrente."""

    def __init__(
        self, transporte: Transporte, oauth: OAuth2Client, config: Config
    ) -> None:
        self._transporte = transporte
        self._oauth = oauth
        self._config = config

    def _get(
        self, rota: str, escopo: str, params: dict[str, Any] | None, contexto: str
    ) -> dict[str, Any]:
        url = self._config.url(rota)
        token = self._oauth.token(escopo)
        try:
            return self._transporte.get_json(
                url, token=token, params=params, contexto=contexto
            )
        except AutenticacaoError:
            # Token revogado/expirado antes do previsto: renova uma única vez.
            self._oauth.invalidar(escopo, token)
            token = self._oauth.token(escopo)
            return self._transporte.get_json(
                url, token=token, params=params, contexto=contexto
            )

    # ------------------------------------------------------------------ extrato

    def extrato_pagina(
        self,
        data_inicio: date | str,
        data_fim: date | str,
        pagina: int = 0,
        tamanho_pagina: int | None = None,
    ) -> PaginaExtrato:
        """Consulta uma única página do extrato (a primeira página é 0).

        Raises:
            ValidacaoError: período ou paginação inválidos.
            ApiError: erro devolvido pela API (ver subclasses).
            ConexaoError: falha de rede.
        """
        inicio, fim = _validar_periodo(data_inicio, data_fim)
        params: dict[str, Any] = {
            'dataInicio': inicio.isoformat(),
            'dataFim': fim.isoformat(),
            'page': _validar_inteiro(pagina, 'pagina', 0),
        }
        if tamanho_pagina is not None:
            params['size'] = _validar_inteiro(tamanho_pagina, 'tamanho_pagina', 1)
        corpo = self._get(ROTA_EXTRATO, ESCOPO_EXTRATO, params, 'consultar extrato')
        return PaginaExtrato.from_api(corpo)

    def extrato(
        self,
        data_inicio: date | str,
        data_fim: date | str,
        tamanho_pagina: int | None = None,
    ) -> Extrato:
        """Consulta o extrato do período, reunindo todas as páginas.

        Movimentos repetidos entre páginas (mesmo ``id_movimento``) aparecem
        uma vez só. Se, ao final, faltarem movimentos em relação ao total
        informado pela API — sinal de que o extrato mudou durante a
        paginação —, levanta :class:`RespostaInvalidaError` em vez de
        devolver um extrato incompleto; basta repetir a consulta.

        A verificação parte da premissa de que o extrato só cresce: um
        lançamento não é removido (estorno entra como movimento novo). Com
        inserções, inclusive retroativas, a falta é sempre detectada pela
        contagem; uma remoção simultânea a uma inserção poderia mascará-la.
        """
        inicio, fim = _validar_periodo(data_inicio, data_fim)
        primeira = self.extrato_pagina(inicio, fim, 0, tamanho_pagina)
        if primeira.pagina != 0:
            raise RespostaInvalidaError(
                f'Primeira página do extrato veio como {primeira.pagina}.'
            )
        if primeira.total_paginas > LIMITE_PAGINAS:
            raise RespostaInvalidaError(
                f'Extrato com {primeira.total_paginas} páginas excede o limite '
                f'de {LIMITE_PAGINAS}: reduza o período ou aumente tamanho_pagina.'
            )

        movimentos: list[Movimento] = []
        vistos: set[str] = set()
        total_esperado = primeira.total_movimentos

        varias_paginas = primeira.total_paginas > 1

        def acumular(pagina: PaginaExtrato) -> None:
            for movimento in pagina.movimentos:
                if movimento.id_movimento is None:
                    # Sem ID não dá para deduplicar: um movimento deslocado
                    # entre páginas contaria duas vezes e esconderia uma falta.
                    if varias_paginas:
                        raise RespostaInvalidaError(
                            'Movimento sem idMovimento em extrato paginado: '
                            'não é possível garantir que esteja completo.'
                        )
                elif movimento.id_movimento in vistos:
                    continue
                else:
                    vistos.add(movimento.id_movimento)
                movimentos.append(movimento)

        acumular(primeira)
        for numero in range(1, primeira.total_paginas):
            pagina = self.extrato_pagina(inicio, fim, numero, tamanho_pagina)
            if pagina.pagina != numero:
                raise RespostaInvalidaError(
                    f'Pedida a página {numero} do extrato, veio a {pagina.pagina}.'
                )
            if pagina.saldo_anterior != primeira.saldo_anterior:
                raise RespostaInvalidaError(
                    'O saldo anterior mudou durante a paginação '
                    f'({primeira.saldo_anterior} → {pagina.saldo_anterior}); '
                    'repita a consulta.'
                )
            total_esperado = max(total_esperado, pagina.total_movimentos)
            acumular(pagina)

        if len(movimentos) < total_esperado:
            raise RespostaInvalidaError(
                f'Extrato incompleto: {len(movimentos)} de {total_esperado} '
                'movimentos. O extrato pode ter mudado durante a paginação; '
                'repita a consulta.'
            )
        return Extrato(
            data_inicio=inicio,
            data_fim=fim,
            saldo_anterior=primeira.saldo_anterior,
            movimentos=movimentos,
        )

    # -------------------------------------------------------------------- saldo

    def saldo(self) -> Saldo:
        """Consulta o saldo atual da conta."""
        corpo = self._get(ROTA_SALDO, ESCOPO_SALDO, None, 'consultar saldo')
        return Saldo.from_api(corpo)
