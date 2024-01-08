import requests
import structlog
import base64

from urllib.parse import urlparse
from django.conf import settings
from django.core.cache import caches
from django.utils.translation import ugettext as _
from jwkest.jwt import JWT
from rest_framework.exceptions import AuthenticationFailed

from oidc_auth.authentication import BearerTokenAuthentication
from oidc_auth.settings import api_settings as oidc_auth_settings
from oidc_auth.util import cache


LOG = structlog.get_logger()
WELL_KNOWN_CONFIG_CACHE_TTL = oidc_auth_settings.OIDC_BEARER_TOKEN_EXPIRATION_TIME
CACHE = caches['default']
OIDC_SUB_PREFIX = 'oidc-sub-'


class JWTAccessTokenAuthentication(BearerTokenAuthentication):
    """Use for Bearer token in JWT format. It allows multiple OIDC providers support."""

    @staticmethod
    def extract_issuer(token):
        data = JWT().unpack(token).payload()
        return data.get('iss').rstrip('/')

    @cache(ttl=WELL_KNOWN_CONFIG_CACHE_TTL)
    def get_well_known_config(self, provider):
        well_known_config_url = provider.get('well_known_config')
        if not well_known_config_url:
            well_known_config_url = provider['issuer'] + '/.well-known/openid-configuration'
        response = requests.get(well_known_config_url)
        response.raise_for_status()
        return response.json()

    def _get_userinfo(self, token):
        issuer = self.extract_issuer(token)
        LOG.debug("Issuer extracted from token.", issuer=issuer)
        allowed_issuers = {provider['issuer']: provider
                           for provider in settings.SANDBOX_UAG['ALLOWED_OIDC_PROVIDERS']}
        if issuer not in allowed_issuers:
            msg = _('Issuer of the token is not listed in ALLOWED_OIDC_PROVIDERS.')
            raise AuthenticationFailed(msg)

        url = urlparse(issuer)
        if url.scheme != 'https':
            LOG.warn('DANGER! OIDC issuer is not using https protocol.', issuer=issuer)

        provider = allowed_issuers[issuer]
        well_known_config = self.get_well_known_config(provider)
        userinfo_endpoint = provider.get('userinfo_endpoint')
        if not userinfo_endpoint:
            userinfo_endpoint = well_known_config['userinfo_endpoint']
        http_headers = {'Authorization': 'Bearer {0}'.format(token.decode('ascii'))}

        response = requests.get(userinfo_endpoint, headers=http_headers)
        response.raise_for_status()

        return response.json()

    def get_userinfo(self, token):
        sub = ""
        userinfo = None
        try:
            token_decoded = token.decode('ascii')
            payload = token_decoded.split(".")[1]
            payload_bytes = payload.encode("ascii")
            payload_bytes_decoded = base64.b64decode(payload_bytes + b'==')
            payload_string = payload_bytes_decoded.decode("ascii")

            sub_pos = payload_string.find('"sub":"')
            if sub_pos != -1:
                payload_decoded_trim = payload_string[sub_pos + len('"sub":"'):]
                sub = payload_decoded_trim[:payload_decoded_trim.find('"')]
                userinfo = CACHE.get(OIDC_SUB_PREFIX + sub)
        except Exception as e:
            LOG.warn(f'An exception occurred during parsing of the token: {e}')

        if not userinfo:
            userinfo = self._get_userinfo(token)
            if sub:
                CACHE.set(OIDC_SUB_PREFIX + sub, userinfo,
                          oidc_auth_settings.OIDC_BEARER_TOKEN_EXPIRATION_TIME)
            else:
                LOG.warn(
                    'Sub was not found in the token, the result of this authentication will not be cached')
        return userinfo
