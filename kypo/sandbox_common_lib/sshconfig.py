import collections

import structlog

# from yamlize import Map, Typed

LOG = structlog.get_logger()

supported_options = [
    'Host',
    'AddKeysToAgent',
    'AddressFamily',
    'BatchMode',
    'BindAddress',
    'ChallengeResponseAuthentication',
    'CheckHostIP',
    'Cipher',
    'Ciphers',
    'Compression',
    'CompressionLevel',
    'ConnectionAttempts',
    'ConnectTimeout',
    'ControlMaster',
    'ControlPath',
    'DynamicForward',
    'EnableSSHKeysign',
    'EscapeChar',
    'ExitOnForwardFailure',
    'ForwardAgent',
    'ForwardX11',
    'ForwardX11Trusted',
    'GatewayPorts',
    'GlobalKnownHostsFile',
    'GSSAPIAuthentication',
    'GSSAPIKeyExchange',
    'GSSAPIClientIdentity',
    'GSSAPIDelegateCredentials',
    'GSSAPIRenewalForcesRekey',
    'GSSAPITrustDns',
    'HashKnownHosts',
    'HostbasedAuthentication',
    'HostKeyAlgorithms',
    'HostKeyAlias',
    'HostName',
    'IdentitiesOnly',
    'IdentityFile',
    'KbdInteractiveAuthentication',
    'KbdInteractiveDevices',
    'LocalCommand',
    'LocalForward',
    'LogLevel',
    'MACs',
    'NumberOfPasswordPrompts',
    'PasswordAuthentication',
    'PermitLocalCommand',
    'Port',
    'PreferredAuthentications',
    'Protocol',
    'ProxyCommand',
    'ProxyJump',
    'RekeyLimit',
    'RemoteForward',
    'RhostsRSAAuthentication',
    'RSAAuthentication',
    'SendEnv',
    'ServerAliveCountMax',
    'ServerAliveInterval',
    'SmartcardDevice',
    'StrictHostKeyChecking',
    'TCPKeepAlive',
    'Tunnel',
    'TunnelDevice',
    'UsePrivilegedPort',
    'User',
    'UserKnownHostsFile',
    'VerifyHostKeyDNS',
    'VisualHostKey',
    'XAuthLocation',
]


# class Entry(Map):
class Entry(collections.OrderedDict):
    _HOST_OPTION = 'Host'

    # key_type = Typed(str)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.validate()

    # @classmethod
    # def from_yaml(cls, loader, node, _rtd=None):
    #     self = super().from_yaml(loader, node, _rtd)
    #     self.validate()
    #     return self

    def __setitem__(self, key, value):
        self._validate_option(key, value)
        super().__setitem__(key, value)

    def __delitem__(self, key):
        if key == self._HOST_OPTION:
            raise Exception('Cannot delete option \'Host\'')
        super().__delitem__(key)

    def update(self, **kwargs):
        data = collections.OrderedDict(self)
        data.update(**kwargs)
        self.__init__(**data)

    def __str__(self):
        return '{0} {1}\n'.format(self._HOST_OPTION, self[self._HOST_OPTION]) + \
               ''.join(['    {0} {1}\n'.format(key, value)
                        for key, value in sorted(self.items(), key=lambda x: x[0])
                        if value and key in supported_options and key != self._HOST_OPTION])

    @property
    def Host(self):
        return self[self._HOST_OPTION]

    def _validate_option(self, key, value):
        if key not in supported_options:
            raise Exception('Unknown option \'{0}\''.format(key))

        if key == self._HOST_OPTION and not value:
            raise Exception('Option \'Host\' cannot be empty')

        if isinstance(value, str):
            if '\n' in value:
                raise Exception('Unsupported multiline values')

    def validate(self):
        for key, value in self.items():
            self._validate_option(key, value)

        if self._HOST_OPTION not in self:
            raise Exception('Missing option \'Host\'')


class Config:
    def __init__(self):
        self.entries = collections.OrderedDict()

    def add_entry(self, Host, **kwargs):
        if Host in self.entries:
            raise Exception('Host \'{0}\' already in config'.format(Host))
        entry = Entry(Host=Host, **kwargs)
        self.entries[entry.Host] = entry

    def get_hosts(self):
        return self.entries.keys()

    def get_entry(self, pattern):
        for entry in self.entries.values():
            if pattern == entry.Host or pattern in entry.Host.split(' '):
                return entry
        return None

    def update_entry(self, pattern, **kwargs):
        entry = self.get_entry(pattern)
        if not entry:
            raise Exception('pattern \'{0}\' not found'.format(pattern))

        old_host = entry.Host
        entry.update(**kwargs)
        new_host = entry.Host

        if old_host != new_host:
            self.entries = collections.OrderedDict([(key, value) if key != old_host else (new_host, value)
                                                    for key, value in self.entries.items()])

    def __str__(self):
        return '\n'.join([str(entry) for entry in self.entries.values()])
