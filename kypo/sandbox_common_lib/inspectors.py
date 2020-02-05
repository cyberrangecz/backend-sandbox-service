"""
Inspectors for proper documentation schemas generation.
"""
from collections import OrderedDict

from drf_yasg import openapi
from drf_yasg.inspectors import PaginatorInspector, NotHandled

from . import pagination


class PageNumberWithPageSizePaginationInspector(PaginatorInspector):
    """Provides response schema pagination wrapping for PageNumberWithPageSizePagination."""
    def get_paginated_response(self, paginator, response_schema):
        assert response_schema.type == openapi.TYPE_ARRAY, "array return expected for paged response"
        if not isinstance(paginator, pagination.PageNumberWithPageSizePagination):
            return NotHandled

        paged_schema = openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties=OrderedDict((
                ('page', openapi.Schema(type=openapi.TYPE_INTEGER)),
                ('page_size', openapi.Schema(type=openapi.TYPE_INTEGER)),
                ('page_count', openapi.Schema(type=openapi.TYPE_INTEGER)),
                ('count', openapi.Schema(type=openapi.TYPE_INTEGER, format=openapi.FORMAT_URI)),
                ('total_count', openapi.Schema(type=openapi.TYPE_INTEGER, format=openapi.FORMAT_URI)),
                ('results', response_schema),
            )),
            required=['results', 'count']
        )
        return paged_schema
