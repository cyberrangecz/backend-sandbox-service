from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from collections import OrderedDict


class PageNumberWithPageSizePagination(PageNumberPagination):
    """Custom pagination class with page size specification."""
    page_size_query_param = "page_size"

    def get_paginated_response(self, data):
        """Override base class method and extend it with extra args."""
        return Response(OrderedDict([
            ('page', self.page.number),
            ('page_size', super().get_page_size(self.request)),
            ('page_count', self.page.paginator.num_pages),
            ('count', len(self.page)),
            ('total_count', self.page.paginator.count),
            ('results', data),
        ]))
