"""
Output view mixins for compressed responses.
"""

from typing import Any

from django.db.models import QuerySet
from rest_framework.response import Response

from crczp.sandbox_common_lib import utils


class CompressedOutputMixin:  # pylint: disable=too-few-public-methods
    """Mixin that provides a helper for building compressed output responses."""

    def create_outputs_response(self, outputs_queryset: QuerySet[Any], from_row: int) -> Response:
        """
        Create a compressed response for outputs endpoints.

        :param outputs_queryset: QuerySet of output objects with 'content' field
        :param from_row: The from_row parameter for pagination
        :return: Compressed Response with content and rows
        """
        outputs = outputs_queryset.filter(id__gt=from_row).order_by('id')

        content_lines = [output.content for output in outputs]
        content = '\n'.join(content_lines) if content_lines else ''

        if from_row == 0:
            content = content.lstrip()

        last_output = outputs.last()
        rows = last_output.id if last_output is not None else from_row

        return utils.create_compressed_response({'content': content, 'rows': rows})
