import drf_yasg.openapi as openapi


USER_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    description="User that created this object",
    properties={
        'id': openapi.Schema(type=openapi.TYPE_INTEGER),
        'sub': openapi.Schema(type=openapi.TYPE_STRING),
        'full_name': openapi.Schema(type=openapi.TYPE_STRING),
        'given_name': openapi.Schema(type=openapi.TYPE_STRING),
        'family_name': openapi.Schema(type=openapi.TYPE_STRING),
        'mail': openapi.Schema(type=openapi.TYPE_STRING),
    }
)

HARDWARE_USAGE_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        'vcpu': openapi.Schema(type=openapi.TYPE_STRING),
        'ram': openapi.Schema(type=openapi.TYPE_STRING),
        'instances': openapi.Schema(type=openapi.TYPE_STRING),
        'network': openapi.Schema(type=openapi.TYPE_STRING),
        'subnet': openapi.Schema(type=openapi.TYPE_STRING),
        'port': openapi.Schema(type=openapi.TYPE_STRING),
    }
)

SANDBOX_DEFINITION_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    title='Definition',
    description='Definition(id, name, url, rev, created_by)',
    properties={
        'id': openapi.Schema(type=openapi.TYPE_INTEGER),
        'name': openapi.Schema(type=openapi.TYPE_STRING),
        'url': openapi.Schema(type=openapi.TYPE_STRING, description='SSH git URL of the definition'),
        'rev': openapi.Schema(type=openapi.TYPE_STRING, description='Git revision used'),
        'created_by': USER_SCHEMA,
    },
    required=['url', 'rev']
)

DEFINITION_REQUEST_BODY = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        'url': openapi.Schema(type=openapi.TYPE_STRING, description='SSH git URL of the definition'),
        'rev': openapi.Schema(type=openapi.TYPE_STRING, description='Git revision used'),
    },
    required=['url', 'rev']
)

POOL_RESPONSE_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    title='Pool',
    description='Pool(id, definition, max_size, size, private_management_key, '
                'public_management_key, management_certificate, uuid, rev, rev_sha, created_by)',
    properties={
        'id': openapi.Schema(type=openapi.TYPE_INTEGER, read_only=True),
        'definition_id': openapi.Schema(type=openapi.TYPE_INTEGER, description='Sandbox definition ID'),
        'size': openapi.Schema(type=openapi.TYPE_INTEGER, description='Current number of SandboxAllocationUnits',
                               read_only=True, default=0),
        'max_size': openapi.Schema(type=openapi.TYPE_INTEGER,
                                   description='Maximum number of SandboxAllocationUnits'),
        'lock_id': openapi.Schema(type=openapi.TYPE_INTEGER, read_only=True),
        'rev': openapi.Schema(type=openapi.TYPE_STRING, description='Name of used git branch',
                              read_only=True),
        'rev_sha': openapi.Schema(type=openapi.TYPE_STRING, description='SHA of used git branch',
                                  read_only=True),
        'created_by': USER_SCHEMA,
        'hardware_usage': HARDWARE_USAGE_SCHEMA,
        'definition': SANDBOX_DEFINITION_SCHEMA,
    },
    required=['definition_id', 'max_size']
)

POOL_REQUEST_BODY = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        'definition_id': openapi.Schema(type=openapi.TYPE_INTEGER, description='Sandbox definition ID'),
        'max_size': openapi.Schema(type=openapi.TYPE_INTEGER,
                                   description='Maximum number of SandboxAllocationUnits'),
    },
    required=['definition_id', 'max_size']
)


def list_response(schema):
    return openapi.Response(
        description='Successful response',
        schema=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'page': openapi.Schema(type=openapi.TYPE_INTEGER),
                'page_size': openapi.Schema(type=openapi.TYPE_INTEGER),
                'page_count': openapi.Schema(type=openapi.TYPE_INTEGER),
                'count': openapi.Schema(type=openapi.TYPE_INTEGER),
                'total_count': openapi.Schema(type=openapi.TYPE_INTEGER),
                'results': openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=schema
                ),
            }
        )
    )
