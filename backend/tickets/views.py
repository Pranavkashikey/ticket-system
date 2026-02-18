from rest_framework import generics, filters
from django_filters.rest_framework import DjangoFilterBackend
from .models import Ticket
from .serializers import TicketSerializer
from rest_framework.views import APIView
from rest_framework.response import Response
from django.db.models import Count, Avg
from django.db.models.functions import TruncDate
from django.utils.timezone import now
from datetime import timedelta

import os
import json
from openai import OpenAI



def rule_based_classification(description):
    text = description.lower()

    # CATEGORY RULES
    if any(word in text for word in ["payment", "refund", "invoice", "billing", "charge"]):
        category = "billing"
    elif any(word in text for word in ["error", "bug", "crash", "issue", "not working"]):
        category = "technical"
    elif any(word in text for word in ["login", "password", "account", "signup"]):
        category = "account"
    else:
        category = "general"

    # PRIORITY RULES
    if any(word in text for word in ["urgent", "immediately", "asap", "critical", "blocked"]):
        priority = "critical"
    elif any(word in text for word in ["important", "high"]):
        priority = "high"
    elif any(word in text for word in ["slow", "delay"]):
        priority = "medium"
    else:
        priority = "low"

    return category, priority


class TicketListCreateView(generics.ListCreateAPIView):
    queryset = Ticket.objects.all()
    serializer_class = TicketSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["category", "priority", "status"]
    search_fields = ["title", "description"]


class TicketUpdateView(generics.UpdateAPIView):
    queryset = Ticket.objects.all()
    serializer_class = TicketSerializer


class TicketStatsView(APIView):

    def get(self, request):
        total = Ticket.objects.count()
        open_count = Ticket.objects.filter(status="open").count()

        priority_data = Ticket.objects.values("priority") \
            .annotate(count=Count("id"))

        category_data = Ticket.objects.values("category") \
            .annotate(count=Count("id"))

        last_30_days = now() - timedelta(days=30)

        avg_per_day = Ticket.objects.filter(created_at__gte=last_30_days) \
            .annotate(day=TruncDate("created_at")) \
            .values("day") \
            .annotate(count=Count("id")) \
            .aggregate(avg=Avg("count"))["avg"] or 0

        return Response({
            "total_tickets": total,
            "open_tickets": open_count,
            "avg_tickets_per_day": round(avg_per_day, 2),
            "priority_breakdown": {
                item["priority"]: item["count"] for item in priority_data
            },
            "category_breakdown": {
                item["category"]: item["count"] for item in category_data
            }
        })
        
        
class TicketClassifyView(APIView):

    def post(self, request):
        description = request.data.get("description")

        if not description:
            return Response(
                {"error": "Description is required"},
                status=400
            )

        try:
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

            prompt = f"""
You are a support ticket classifier.

Categories:
billing, technical, account, general

Priorities:
low, medium, high, critical

Respond ONLY in valid JSON like:
{{
  "category": "billing",
  "priority": "medium"
}}

Ticket:
{description}
"""

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0
            )

            content = response.choices[0].message.content.strip()
            data = json.loads(content)

            category = data.get("category")
            priority = data.get("priority")

            return Response({
                "suggested_category": category,
                "suggested_priority": priority,
                "source": "llm"
            })

        except Exception as e:
            print("LLM failed. Using fallback:", e)

            # 🔥 FALLBACK LOGIC
            category, priority = rule_based_classification(description)

            return Response({
                "suggested_category": category,
                "suggested_priority": priority,
                "source": "fallback"
            })
