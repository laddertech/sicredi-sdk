"""SDK Python para as APIs de parceiros do Sicredi."""

from sicredi.auth import MemoryTokenStore, Token, TokenStore
from sicredi.client import Sicredi
from sicredi.config import Ambiente
from sicredi.exceptions import (
    ApiError,
    AutenticacaoError,
    CertificadoError,
    ConexaoError,
    ConfiguracaoError,
    LimiteRequisicoesError,
    NaoEncontradoError,
    PermissaoError,
    RequisicaoInvalidaError,
    RespostaInvalidaError,
    ServidorError,
    SicrediError,
    ValidacaoError,
)
from sicredi.models import Extrato, Movimento, PaginaExtrato, Saldo

__version__ = '0.1.0'

__all__ = [
    'Ambiente',
    'ApiError',
    'AutenticacaoError',
    'CertificadoError',
    'ConexaoError',
    'ConfiguracaoError',
    'Extrato',
    'LimiteRequisicoesError',
    'MemoryTokenStore',
    'Movimento',
    'NaoEncontradoError',
    'PaginaExtrato',
    'PermissaoError',
    'RequisicaoInvalidaError',
    'RespostaInvalidaError',
    'Saldo',
    'ServidorError',
    'Sicredi',
    'SicrediError',
    'Token',
    'TokenStore',
    'ValidacaoError',
    '__version__',
]
