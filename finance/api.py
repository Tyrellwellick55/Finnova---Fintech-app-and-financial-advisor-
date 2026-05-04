from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone

from .models import (
    Income,
    Expense,
    Budget,
    FinancialGoal,
    FinancialMetric,
    BudgetCategory,
    TaxRecord,
    Investment,
    Debt,
    FinancialReport,
)
from .serializers import (
    IncomeSerializer, ExpenseSerializer, BudgetSerializer,
    FinancialGoalSerializer, DashboardSerializer, ReportSerializer,
    InvestmentSerializer, DebtSerializer, FinancialMetricSerializer,
    BudgetCategorySerializer, TaxRecordSerializer
)
from .services.finance_engine import FinanceEngine
from .services.wallet_intelligence import WalletIntelligence

class IncomeViewSet(viewsets.ModelViewSet):
    queryset = Income.objects.all()
    serializer_class = IncomeSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['category', 'date', 'is_recurring', 'is_verified']
    
    def get_queryset(self):
        return self.queryset.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    
    @action(detail=False, methods=['get'])
    def monthly_summary(self, request):
        today = timezone.now()
        summary = FinanceEngine.calculate_monthly_summary(
            request.user, today.year, today.month
        )
        return Response(summary)

class ExpenseViewSet(viewsets.ModelViewSet):
    queryset = Expense.objects.all()
    serializer_class = ExpenseSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['category', 'date', 'payment_method', 'is_verified']
    
    def get_queryset(self):
        return self.queryset.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    
    @action(detail=False, methods=['get'])
    def recent(self, request):
        expenses = self.get_queryset().order_by('-date', '-created_at')[:10]
        serializer = self.get_serializer(expenses, many=True)
        return Response(serializer.data)

class BudgetViewSet(viewsets.ModelViewSet):
    queryset = Budget.objects.all()
    serializer_class = BudgetSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return self.queryset.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    
    @action(detail=True, methods=['post'])
    def update_spending(self, request, pk=None):
        budget = self.get_object()
        budget.update_spending()
        return Response({'status': 'spending updated', 'current_spending': budget.current_spending})

class FinancialGoalViewSet(viewsets.ModelViewSet):
    queryset = FinancialGoal.objects.all()
    serializer_class = FinancialGoalSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return self.queryset.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    
    @action(detail=True, methods=['post'])
    def update_progress(self, request, pk=None):
        goal = self.get_object()
        amount = request.data.get('amount', 0)
        
        try:
            amount = float(amount)
            if amount <= 0:
                return Response({'error': 'Amount must be positive'}, status=400)
            
            goal.current_amount += amount
            goal.save()
            
            return Response({
                'success': True,
                'current_amount': goal.current_amount,
                'progress_percentage': goal.progress_percentage
            })
        except ValueError:
            return Response({'error': 'Invalid amount'}, status=400)

class DashboardAPIView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            # Get dashboard data
            today = timezone.now()
            summary = FinanceEngine.calculate_monthly_summary(
                request.user, today.year, today.month
            )
            
            # Get financial health
            health = FinanceEngine.calculate_financial_health(request.user)
            
            # Get wallet suggestions
            suggestions = WalletIntelligence.wallet_suggestions(request.user)
            
            # Get AI insights
            insights = FinanceEngine.generate_ai_insights(request.user)
            
            # Compile dashboard data
            dashboard_data = {
                'summary': summary,
                'financial_health': health,
                'suggestions': suggestions,
                'insights': insights,
                'timestamp': timezone.now()
            }
            
            serializer = DashboardSerializer(dashboard_data)
            return Response(serializer.data)
            
        except Exception as e:
            return Response({'error': str(e)}, status=500)

class AutoProtectAPIView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            result = WalletIntelligence.auto_protect_savings(request.user)
            return Response(result)
        except Exception as e:
            return Response({'error': str(e)}, status=500)

class AnalyticsAPIView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            # Get period from query params
            days = int(request.GET.get('days', 30))
            
            # Generate analytics
            insights = FinanceEngine.generate_ai_insights(request.user, days)
            predictions = FinanceEngine.predict_future_expenses(request.user)
            health = FinanceEngine.calculate_financial_health(request.user)
            
            return Response({
                'insights': insights,
                'predictions': predictions,
                'financial_health': health,
                'period_days': days
            })
        except Exception as e:
            return Response({'error': str(e)}, status=500)

class SyncAPIView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            days_back = int(request.data.get('days_back', 30))
            result = FinanceEngine.sync_with_payments_core(request.user, days_back)
            return Response(result)
        except Exception as e:
            return Response({'error': str(e)}, status=500)

class ReportViewSet(viewsets.ModelViewSet):
    queryset = FinancialReport.objects.all()
    serializer_class = ReportSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return self.queryset.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    
    @action(detail=True, methods=['post'])
    def generate(self, request, pk=None):
        report = self.get_object()
        # Trigger report generation
        return Response({'status': 'generation started'})

class InvestmentViewSet(viewsets.ModelViewSet):
    queryset = Investment.objects.all()
    serializer_class = InvestmentSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return self.queryset.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

class DebtViewSet(viewsets.ModelViewSet):
    queryset = Debt.objects.all()
    serializer_class = DebtSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return self.queryset.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)