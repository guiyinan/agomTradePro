from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.composition import make_get_forecast_scoreboard_use_case


class ForecastScoreboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):  # type: ignore[no-untyped-def]
        return Response(
            make_get_forecast_scoreboard_use_case().execute(
                request.query_params.get("group_by") or None
            )
        )

