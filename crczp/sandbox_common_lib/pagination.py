"""Custom pagination classes for the sandbox service API."""

from collections import OrderedDict

from django.db.models.query import QuerySet
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class PageNumberWithPageSizePagination(PageNumberPagination):
    """Custom pagination class with page size specification."""

    page_size_query_param = 'page_size'
    sort_by_default_param = 'id'
    order_default_param = 'asc'
    sorting_default_values = {}

    def get_schema_operation_parameters(self, view):
        """Extend schema operation parameters with sort_by and order parameters."""
        parameters = super().get_schema_operation_parameters(view)
        parameters += [
            {
                'name': 'sort_by',
                'required': False,
                'in': 'query',
                'description': 'Attribute used to sort result set',
                'schema': {'type': 'string'},
            },
            {
                'name': 'order',
                'required': False,
                'in': 'query',
                'description': 'Sort order',
                'schema': {'type': 'string'},
            },
        ]
        return parameters

    def get_paginated_response(self, data):
        """Override base class method and extend it with extra args."""
        return Response(
            OrderedDict([
                ('page', self.page.number),
                ('page_size', super().get_page_size(self.request)),
                ('page_count', self.page.paginator.num_pages),
                ('count', len(self.page)),
                ('total_count', self.page.paginator.count),
                ('results', data),
            ])
        )

    def paginate_queryset(self, queryset, request, view=None):
        sort_by_param = request.GET.get('sort_by', self.sort_by_default_param)
        order_param = request.GET.get('order', self.order_default_param)

        if isinstance(queryset, QuerySet):
            sort_by_param = '-' + sort_by_param if order_param == 'desc' else sort_by_param
            queryset = queryset.order_by(sort_by_param)
        else:
            queryset = sorted(
                queryset,
                key=lambda item: self._ensure_comparable(
                    item.get(sort_by_param, ''), sort_by_param
                ),
                reverse=order_param == 'desc',
            )
        return super().paginate_queryset(queryset, request, view)

    def _ensure_comparable(self, value, sort_by):
        """
        None values in parameters cause problems with sorting. This method
        replaces None with orderable values in the sorting function.

        If you want to add sorting by a parameter that can be None, adjust
        paginator.sorting_default_values in the given list view
        """
        if value is not None:
            return value

        default = self.sorting_default_values.get(sort_by, None)
        if default is not None:
            return default

        raise ValueError(f'Unexpected None value for the attribute {sort_by}, cannot sort.')
