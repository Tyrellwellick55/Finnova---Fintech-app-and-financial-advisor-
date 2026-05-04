# analytics_ai/models.py
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
import uuid
from decimal import Decimal

User = get_user_model()

class UserFinancialProfile(models.Model):
    """AI-generated financial profile of user"""
    FINANCIAL_PERSONALITY = [
        ('SAVER', 'Saver'),
        ('SPENDER', 'Spender'),
        ('INVESTOR', 'Investor'),
        ('BALANCED', 'Balanced'),
        ('RISK_TAKER', 'Risk Taker'),
        ('CONSERVATIVE', 'Conservative')
    ]
    
    RISK_LEVELS = [
        ('LOW', 'Low Risk'),
        ('MEDIUM', 'Medium Risk'),
        ('HIGH', 'High Risk'),
        ('VERY_HIGH', 'Very High Risk')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='ai_financial_profile')
    
    # Personality and risk
    financial_personality = models.CharField(max_length=20, choices=FINANCIAL_PERSONALITY, default='BALANCED')
    risk_level = models.CharField(max_length=20, choices=RISK_LEVELS, default='MEDIUM')
    savings_score = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(100)], default=50)
    
    # Spending patterns
    spending_patterns = models.JSONField(default=dict, blank=True)
    top_categories = models.JSONField(default=list, blank=True)
    spending_habits = models.JSONField(default=dict, blank=True)
    
    # Income analysis
    income_sources = models.JSONField(default=list, blank=True)
    income_stability = models.CharField(max_length=20, choices=[
        ('STABLE', 'Stable'),
        ('VOLATILE', 'Volatile'),
        ('GROWING', 'Growing'),
        ('DECLINING', 'Declining')
    ], default='STABLE')
    income_predictability = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)  # 0-100%
    
    # Debt profile
    debt_profile = models.JSONField(default=dict, blank=True)
    debt_to_income_ratio = models.DecimalField(max_digits=10, decimal_places=4, default=0.00)
    debt_management_score = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(100)], default=50)
    
    # Investment profile
    investment_profile = models.JSONField(default=dict, blank=True)
    investment_knowledge = models.CharField(max_length=20, choices=[
        ('BEGINNER', 'Beginner'),
        ('INTERMEDIATE', 'Intermediate'),
        ('ADVANCED', 'Advanced'),
        ('EXPERT', 'Expert')
    ], default='BEGINNER')
    investment_risk_tolerance = models.CharField(max_length=20, choices=RISK_LEVELS, default='MEDIUM')
    
    # Behavioral insights
    behavioral_traits = models.JSONField(default=list, blank=True)
    financial_literacy = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)  # 0-100%
    goal_oriented = models.BooleanField(default=False)
    
    # Predictions
    predicted_cashflow = models.JSONField(default=dict, blank=True)
    predicted_expenses = models.JSONField(default=dict, blank=True)
    predicted_income = models.JSONField(default=dict, blank=True)
    
    # Recommendations
    personalized_recommendations = models.JSONField(default=list, blank=True)
    improvement_areas = models.JSONField(default=list, blank=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    analyzed_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-analyzed_at']
    
    def __str__(self):
        return f"AI Profile - {self.user.username} - {self.financial_personality}"
    
    def analyze(self):
        """Analyze user's financial data and update profile"""
        from .services.ai_analyzer import AIAnalyzer
        analysis = AIAnalyzer.analyze_user_finances(self.user)
        
        # Update fields
        self.financial_personality = analysis.get('financial_personality', 'BALANCED')
        self.risk_level = analysis.get('risk_level', 'MEDIUM')
        self.savings_score = analysis.get('savings_score', 50)
        
        self.spending_patterns = analysis.get('spending_patterns', {})
        self.top_categories = analysis.get('top_categories', [])
        self.spending_habits = analysis.get('spending_habits', {})
        
        self.income_sources = analysis.get('income_sources', [])
        self.income_stability = analysis.get('income_stability', 'STABLE')
        self.income_predictability = analysis.get('income_predictability', 0)
        
        self.debt_profile = analysis.get('debt_profile', {})
        self.debt_to_income_ratio = analysis.get('debt_to_income_ratio', 0)
        self.debt_management_score = analysis.get('debt_management_score', 50)
        
        self.investment_profile = analysis.get('investment_profile', {})
        self.investment_knowledge = analysis.get('investment_knowledge', 'BEGINNER')
        self.investment_risk_tolerance = analysis.get('investment_risk_tolerance', 'MEDIUM')
        
        self.behavioral_traits = analysis.get('behavioral_traits', [])
        self.financial_literacy = analysis.get('financial_literacy', 0)
        self.goal_oriented = analysis.get('goal_oriented', False)
        
        self.predicted_cashflow = analysis.get('predicted_cashflow', {})
        self.predicted_expenses = analysis.get('predicted_expenses', {})
        self.predicted_income = analysis.get('predicted_income', {})
        
        self.personalized_recommendations = analysis.get('recommendations', [])
        self.improvement_areas = analysis.get('improvement_areas', [])
        
        self.analyzed_at = timezone.now()
        self.save()
        
        return analysis

class FinancialInsight(models.Model):
    """AI-generated financial insights"""
    INSIGHT_TYPES = [
        ('SPENDING', 'Spending Insight'),
        ('SAVINGS', 'Savings Insight'),
        ('INVESTMENT', 'Investment Insight'),
        ('DEBT', 'Debt Insight'),
        ('INCOME', 'Income Insight'),
        ('BUDGET', 'Budget Insight'),
        ('TREND', 'Trend Analysis'),
        ('ANOMALY', 'Anomaly Detection'),
        ('OPPORTUNITY', 'Opportunity'),
        ('RISK', 'Risk Alert'),
        ('PATTERN', 'Pattern Recognition'),
        ('PREDICTION', 'Prediction'),
        ('RECOMMENDATION', 'Recommendation'),
        ('COMPARISON', 'Comparison')
    ]
    
    SEVERITY_CHOICES = [
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
        ('CRITICAL', 'Critical')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='financial_insights')
    
    # Insight details
    insight_type = models.CharField(max_length=20, choices=INSIGHT_TYPES, default='SPENDING')
    title = models.CharField(max_length=200)
    description = models.TextField()
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='LOW')
    
    # Data
    related_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    related_percentage = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    comparison_data = models.JSONField(default=dict, blank=True)
    
    # Action
    action_required = models.BooleanField(default=False)
    action_type = models.CharField(max_length=50, blank=True, null=True)
    action_url = models.URLField(blank=True, null=True)
    action_completed = models.BooleanField(default=False)
    
    # Related entities
    related_transactions = models.JSONField(default=list, blank=True)
    related_categories = models.JSONField(default=list, blank=True)
    related_merchants = models.JSONField(default=list, blank=True)
    
    # Status
    is_active = models.BooleanField(default=True)
    is_read = models.BooleanField(default=False)
    is_acknowledged = models.BooleanField(default=False)
    
    # Timing
    insight_date = models.DateField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    action_completed_at = models.DateTimeField(null=True, blank=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ['-created_at', 'severity']
        indexes = [
            models.Index(fields=['user', 'insight_type', 'created_at']),
            models.Index(fields=['severity', 'action_required', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.insight_type} - {self.title} - {self.severity}"
    
    @property
    def category(self):
        """Backward-compatible alias for older templates."""
        return self.insight_type

    def get_severity_color(self):
        """Get color for severity display"""
        severity_colors = {
            'LOW': '#4CAF50',      # Green
            'MEDIUM': '#FFC107',    # Amber
            'HIGH': '#FF9800',      # Orange
            'CRITICAL': '#F44336',  # Red
        }
        return severity_colors.get(self.severity, '#9E9E9E')
    
    def mark_as_read(self):
        """Mark insight as read"""
        self.is_read = True
        self.save()
    
    def acknowledge(self):
        """Acknowledge insight"""
        self.is_acknowledged = True
        self.acknowledged_at = timezone.now()
        self.save()
    
    def complete_action(self):
        """Mark action as completed"""
        self.action_completed = True
        self.action_completed_at = timezone.now()
        self.save()
    
    def is_expired(self):
        """Check if insight is expired"""
        if not self.expires_at:
            return False
        return timezone.now() > self.expires_at
    
    @classmethod
    def generate_insight(cls, user, insight_type, data, trigger_transaction=None):
        """Generate a new insight"""
        from .services.ai_analyzer import AIAnalyzer
        
        insight_data = AIAnalyzer.generate_insight(
            user=user,
            insight_type=insight_type,
            data=data,
            trigger_transaction=trigger_transaction
        )
        
        insight = cls.objects.create(
            user=user,
            insight_type=insight_type,
            title=insight_data['title'],
            description=insight_data['description'],
            severity=insight_data['severity'],
            related_amount=insight_data.get('related_amount'),
            related_percentage=insight_data.get('related_percentage'),
            comparison_data=insight_data.get('comparison_data', {}),
            action_required=insight_data.get('action_required', False),
            action_type=insight_data.get('action_type'),
            action_url=insight_data.get('action_url'),
            related_transactions=insight_data.get('related_transactions', []),
            related_categories=insight_data.get('related_categories', []),
            related_merchants=insight_data.get('related_merchants', []),
            metadata=insight_data.get('metadata', {})
        )
        
        return insight

class PredictiveAlert(models.Model):
    """AI-powered predictive alerts"""
    ALERT_TYPES = [
        ('CASHFLOW', 'Cash Flow Alert'),
        ('BUDGET', 'Budget Alert'),
        ('SAVINGS', 'Savings Alert'),
        ('DEBT', 'Debt Alert'),
        ('INVESTMENT', 'Investment Alert'),
        ('INCOME', 'Income Alert'),
        ('EXPENSE', 'Expense Alert'),
        ('RISK', 'Risk Alert'),
        ('OPPORTUNITY', 'Opportunity Alert'),
        ('TREND', 'Trend Alert')
    ]
    
    CONFIDENCE_LEVELS = [
        ('LOW', 'Low Confidence (< 50%)'),
        ('MEDIUM', 'Medium Confidence (50-75%)'),
        ('HIGH', 'High Confidence (75-90%)'),
        ('VERY_HIGH', 'Very High Confidence (> 90%)')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='predictive_alerts')
    
    # Alert details
    alert_type = models.CharField(max_length=20, choices=ALERT_TYPES, default='CASHFLOW')
    title = models.CharField(max_length=200)
    description = models.TextField()
    
    # Prediction
    predicted_date = models.DateField()
    predicted_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    confidence_level = models.CharField(max_length=20, choices=CONFIDENCE_LEVELS, default='MEDIUM')
    confidence_score = models.DecimalField(max_digits=5, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(100)], default=50.00)
    
    # Impact
    impact_level = models.CharField(max_length=20, choices=[
        ('LOW', 'Low Impact'),
        ('MEDIUM', 'Medium Impact'),
        ('HIGH', 'High Impact'),
        ('CRITICAL', 'Critical Impact')
    ], default='MEDIUM')
    
    # Mitigation
    mitigation_plan = models.JSONField(default=list, blank=True)
    suggested_actions = models.JSONField(default=list, blank=True)
    
    # Status
    is_active = models.BooleanField(default=True)
    is_acknowledged = models.BooleanField(default=False)
    has_occurred = models.BooleanField(default=False)
    
    # Timing
    created_at = models.DateTimeField(auto_now_add=True)
    predicted_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    occurred_at = models.DateTimeField(null=True, blank=True)
    
    # Related data
    related_data = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ['predicted_date', '-confidence_score']
    
    def __str__(self):
        status = "Active" if self.is_active else "Inactive"
        return f"{self.alert_type} - {self.predicted_date} - {self.confidence_score}% - {status}"
    
    @property
    def days_until(self):
        """Days until predicted date"""
        from datetime import date
        return (self.predicted_date - date.today()).days
    
    def mark_as_occurred(self, actual_data=None):
        """Mark prediction as occurred"""
        self.has_occurred = True
        self.occurred_at = timezone.now()
        if actual_data:
            self.metadata['actual_data'] = actual_data
        self.save()
    
    def acknowledge(self):
        """Acknowledge alert"""
        self.is_acknowledged = True
        self.acknowledged_at = timezone.now()
        self.save()
    
    def update_confidence(self, new_score):
        """Update confidence score"""
        self.confidence_score = Decimal(str(new_score))
        
        # Update confidence level
        if new_score >= 90:
            self.confidence_level = 'VERY_HIGH'
        elif new_score >= 75:
            self.confidence_level = 'HIGH'
        elif new_score >= 50:
            self.confidence_level = 'MEDIUM'
        else:
            self.confidence_level = 'LOW'
        
        self.save()
    
    @classmethod
    def predict_cashflow_crisis(cls, user, days_ahead=30):
        """Predict cash flow crisis"""
        from .services.ai_predictor import AIPredictor
        
        prediction = AIPredictor.predict_cashflow_crisis(user, days_ahead)
        
        if prediction['has_crisis']:
            alert = cls.objects.create(
                user=user,
                alert_type='CASHFLOW',
                title=prediction['title'],
                description=prediction['description'],
                predicted_date=prediction['predicted_date'],
                predicted_amount=prediction['predicted_amount'],
                confidence_score=prediction['confidence_score'],
                confidence_level=prediction['confidence_level'],
                impact_level=prediction['impact_level'],
                mitigation_plan=prediction['mitigation_plan'],
                suggested_actions=prediction['suggested_actions'],
                related_data=prediction['related_data'],
                metadata=prediction.get('metadata', {})
            )
            return alert
        
        return None

class SmartRule(models.Model):
    """AI-generated smart rules for automation"""
    CONDITION_TYPES = [
        ('SPENDING', 'Spending Condition'),
        ('INCOME', 'Income Condition'),
        ('BALANCE', 'Balance Condition'),
        ('TIME', 'Time Condition'),
        ('CATEGORY', 'Category Condition'),
        ('AMOUNT', 'Amount Condition'),
        ('PATTERN', 'Pattern Condition'),
        ('LOCATION', 'Location Condition'),
        ('MERCHANT', 'Merchant Condition')
    ]
    
    ACTION_TYPES = [
        ('SAVE', 'Save Money'),
        ('INVEST', 'Make Investment'),
        ('ALERT', 'Send Alert'),
        ('BLOCK', 'Block Transaction'),
        ('CATEGORIZE', 'Auto-Categorize'),
        ('REVIEW', 'Flag for Review'),
        ('TRANSFER', 'Transfer Funds'),
        ('ADJUST_BUDGET', 'Adjust Budget'),
        ('CREATE_GOAL', 'Create Goal'),
        ('PAY_DEBT', 'Pay Debt'),
        ('SUGGEST', 'Make Suggestion')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='smart_rules')
    
    # Rule details
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    condition_type = models.CharField(max_length=20, choices=CONDITION_TYPES)
    condition_value = models.JSONField(default=dict)
    action_type = models.CharField(max_length=20, choices=ACTION_TYPES)
    action_value = models.JSONField(default=dict)
    
    # AI generated
    is_ai_generated = models.BooleanField(default=True)
    ai_confidence = models.DecimalField(max_digits=5, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(100)], default=0.00)
    
    # Status
    is_active = models.BooleanField(default=True)
    priority = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(10)])
    
    # Performance
    execution_count = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    last_executed = models.DateTimeField(null=True, blank=True)
    last_success = models.DateTimeField(null=True, blank=True)
    
    # Linked entities
    linked_insight = models.ForeignKey(FinancialInsight, on_delete=models.SET_NULL, null=True, blank=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['priority', '-created_at']
    
    def __str__(self):
        source = "AI" if self.is_ai_generated else "User"
        return f"{self.name} - {self.condition_type} → {self.action_type} - {source}"
    
    def execute(self, trigger_data=None):
        """Execute smart rule"""
        from .services.ai_automation import AIAutomation
        
        try:
            result = AIAutomation.execute_smart_rule(self, trigger_data)
            self.execution_count += 1
            self.success_count += 1
            self.last_executed = timezone.now()
            self.last_success = timezone.now()
            self.save()
            return result
        except Exception as e:
            self.execution_count += 1
            self.last_executed = timezone.now()
            self.save()
            raise e
    
    def check_condition(self, data):
        """Check if condition is met"""
        from .services.ai_automation import AIAutomation
        return AIAutomation.check_condition(self.condition_type, self.condition_value, data)
    
    def get_success_rate(self):
        """Calculate success rate"""
        if self.execution_count == 0:
            return Decimal('0.00')
        return (self.success_count / self.execution_count) * 100
    
    @classmethod
    def generate_from_insight(cls, user, insight):
        """Generate smart rule from insight"""
        from .services.ai_automation import AIAutomation
        
        rule_data = AIAutomation.generate_rule_from_insight(user, insight)
        
        if rule_data:
            rule = cls.objects.create(
                user=user,
                name=rule_data['name'],
                description=rule_data['description'],
                condition_type=rule_data['condition_type'],
                condition_value=rule_data['condition_value'],
                action_type=rule_data['action_type'],
                action_value=rule_data['action_value'],
                is_ai_generated=True,
                ai_confidence=rule_data['confidence'],
                priority=rule_data.get('priority', 1),
                linked_insight=insight,
                metadata=rule_data.get('metadata', {})
            )
            return rule
        
        return None

class AISession(models.Model):
    """AI chat/advice sessions"""
    SESSION_TYPES = [
        ('CHAT', 'Chat Session'),
        ('ADVICE', 'Financial Advice'),
        ('ANALYSIS', 'Financial Analysis'),
        ('PLANNING', 'Financial Planning'),
        ('EDUCATION', 'Financial Education'),
        ('SUPPORT', 'Customer Support')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ai_sessions')
    
    # Session details
    session_type = models.CharField(max_length=20, choices=SESSION_TYPES, default='CHAT')
    title = models.CharField(max_length=200, blank=True, null=True)
    
    # Conversation
    conversation_history = models.JSONField(default=list, blank=True)
    context_data = models.JSONField(default=dict, blank=True)
    
    # Analysis results
    analysis_data = models.JSONField(default=dict, blank=True)
    recommendations = models.JSONField(default=list, blank=True)
    insights_generated = models.JSONField(default=list, blank=True)
    
    # Status
    is_active = models.BooleanField(default=True)
    is_completed = models.BooleanField(default=False)
    
    # Timing
    started_at = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    
    # Performance
    message_count = models.PositiveIntegerField(default=0)
    ai_response_time_avg = models.DecimalField(max_digits=10, decimal_places=3, default=0.000)  # seconds
    
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ['-last_activity']
    
    def __str__(self):
        status = "Active" if self.is_active else "Completed"
        return f"{self.session_type} - {self.user.username} - {status}"
    
    def add_message(self, role, content, metadata=None):
        """Add message to conversation"""
        message = {
            'role': role,  # 'user' or 'assistant'
            'content': content,
            'timestamp': timezone.now().isoformat(),
            'metadata': metadata or {}
        }
        
        self.conversation_history.append(message)
        self.message_count += 1
        self.last_activity = timezone.now()
        self.save()
        
        return message
    
    def get_last_messages(self, count=10):
        """Get last N messages"""
        return self.conversation_history[-count:] if self.conversation_history else []
    
    def complete(self):
        """Mark session as completed"""
        self.is_active = False
        self.is_completed = True
        self.ended_at = timezone.now()
        self.save()
    
    def get_summary(self):
        """Get session summary"""
        return {
            'session_id': str(self.id),
            'session_type': self.session_type,
            'message_count': self.message_count,
            'started_at': self.started_at.isoformat(),
            'ended_at': self.ended_at.isoformat() if self.ended_at else None,
            'duration': (self.ended_at - self.started_at).total_seconds() if self.ended_at else None,
            'insights_count': len(self.insights_generated),
            'recommendations_count': len(self.recommendations)
        }

class AIFinancialGoal(models.Model):
    """AI-generated financial goals"""
    GOAL_TYPES = [
        ('SAVINGS', 'Savings Goal'),
        ('DEBT', 'Debt Reduction'),
        ('INVESTMENT', 'Investment Goal'),
        ('EMERGENCY_FUND', 'Emergency Fund'),
        ('RETIREMENT', 'Retirement Planning'),
        ('EDUCATION', 'Education Fund'),
        ('PURCHASE', 'Major Purchase'),
        ('INCOME', 'Income Growth'),
        ('NET_WORTH', 'Net Worth Target'),
        ('FINANCIAL_FREEDOM', 'Financial Freedom')
    ]
    
    COMPLEXITY_LEVELS = [
        ('SIMPLE', 'Simple'),
        ('INTERMEDIATE', 'Intermediate'),
        ('COMPLEX', 'Complex'),
        ('ADVANCED', 'Advanced')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ai_financial_goals')
    
    # Goal details
    goal_type = models.CharField(max_length=20, choices=GOAL_TYPES, default='SAVINGS')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    
    # Targets
    target_value = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    current_value = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    target_date = models.DateField()
    
    # AI assessment
    complexity = models.CharField(max_length=20, choices=COMPLEXITY_LEVELS, default='INTERMEDIATE')
    feasibility_score = models.DecimalField(max_digits=5, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(100)], default=50.00)
    priority_score = models.DecimalField(max_digits=5, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(100)], default=50.00)
    
    # Plan
    action_plan = models.JSONField(default=list, blank=True)
    milestones = models.JSONField(default=list, blank=True)
    resources = models.JSONField(default=list, blank=True)
    
    # Tracking
    progress_tracking = models.JSONField(default=dict, blank=True)
    last_progress_update = models.DateTimeField(null=True, blank=True)
    next_checkpoint = models.DateField(null=True, blank=True)
    
    # Status
    status = models.CharField(max_length=20, choices=[
        ('PROPOSED', 'Proposed'),
        ('ACCEPTED', 'Accepted'),
        ('IN_PROGRESS', 'In Progress'),
        ('ON_HOLD', 'On Hold'),
        ('ACHIEVED', 'Achieved'),
        ('ADJUSTED', 'Adjusted'),
        ('ABANDONED', 'Abandoned')
    ], default='PROPOSED')
    
    # Linked to finance module goal
    linked_finance_goal = models.ForeignKey('finance.FinancialGoal', on_delete=models.SET_NULL, null=True, blank=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['priority_score', 'target_date']
    
    def __str__(self):
        return f"{self.name} - {self.target_value} by {self.target_date} - {self.user.username}"
    
    @property
    def progress_percentage(self):
        """Calculate progress percentage"""
        if self.target_value == 0:
            return 0
        return (self.current_value / self.target_value) * 100
    
    @property
    def days_remaining(self):
        """Days remaining to target date"""
        from datetime import date
        return (self.target_date - date.today()).days
    
    @property
    def required_monthly_amount(self):
        """Required monthly amount to reach goal"""
        months = max(self.days_remaining / 30, 1)
        remaining = self.target_value - self.current_value
        return remaining / months
    
    def update_progress(self, new_value, update_reason=None):
        """Update goal progress"""
        self.current_value = Decimal(new_value)
        self.last_progress_update = timezone.now()
        
        # Update progress tracking
        if 'progress_history' not in self.progress_tracking:
            self.progress_tracking['progress_history'] = []
        
        self.progress_tracking['progress_history'].append({
            'date': timezone.now().isoformat(),
            'value': float(new_value),
            'percentage': float(self.progress_percentage),
            'reason': update_reason
        })
        
        # Check if achieved
        if self.current_value >= self.target_value:
            self.status = 'ACHIEVED'
        
        self.save()
    
    def accept(self):
        """Accept AI-generated goal"""
        self.status = 'ACCEPTED'
        
        # Create corresponding goal in finance module
        from finance.models import FinancialGoal
        
        finance_goal = FinancialGoal.objects.create(
            user=self.user,
            name=self.name,
            goal_type=self.goal_type,
            target_amount=self.target_value,
            current_amount=self.current_value,
            target_date=self.target_date,
            status='IN_PROGRESS',
            priority='HIGH' if self.priority_score >= 75 else 'MEDIUM',
            suggested_monthly_saving=self.required_monthly_amount,
            notes=self.description
        )
        
        self.linked_finance_goal = finance_goal
        self.save()
        
        return finance_goal
    
    def adjust_target(self, new_target_value, new_target_date=None, reason=None):
        """Adjust goal target"""
        old_target = self.target_value
        old_date = self.target_date
        
        self.target_value = Decimal(new_target_value)
        if new_target_date:
            self.target_date = new_target_date
        
        self.status = 'ADJUSTED'
        
        # Record adjustment
        if 'adjustments' not in self.metadata:
            self.metadata['adjustments'] = []
        
        self.metadata['adjustments'].append({
            'date': timezone.now().isoformat(),
            'old_target': float(old_target),
            'new_target': float(new_target_value),
            'old_date': old_date.isoformat(),
            'new_date': self.target_date.isoformat(),
            'reason': reason
        })
        
        self.save()
        
        # Update linked finance goal if exists
        if self.linked_finance_goal:
            self.linked_finance_goal.target_amount = self.target_value
            if new_target_date:
                self.linked_finance_goal.target_date = new_target_date
            self.linked_finance_goal.save()