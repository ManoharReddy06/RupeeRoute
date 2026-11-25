import datetime
from decimal import Decimal
from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    full_name = models.CharField(max_length=120, blank=True)
    age = models.PositiveIntegerField(null=True, blank=True)
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)
    is_profile_setup = models.BooleanField(default=False)
    is_viewer = models.BooleanField(default=False)
    viewer_of = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE, related_name='viewers')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username}'s Profile"

    @property
    def display_name(self):
        return self.full_name if self.full_name else self.user.username

    @property
    def initials(self):
        name = self.display_name.strip()
        parts = name.split()
        if len(parts) >= 2:
            return f"{parts[0][0]}{parts[1][0]}".upper()
        return name[:2].upper() if name else "ME"


class PersonalExpense(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='expenses')
    date = models.DateField(default=datetime.date.today)
    description = models.CharField(max_length=255, help_text="e.g. Curd, Rapido, Room Rent, Shopping")
    category = models.CharField(max_length=100, default='Food', help_text="e.g. Food, Travel, Rent, Shopping, Recharge")
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']
        indexes = [
            models.Index(fields=['user', 'date'], name='pe_user_date_idx'),
        ]

    def __str__(self):
        return f"{self.date} - {self.description} (₹{self.amount})"


class SharingGroup(models.Model):
    """
    Represents a shared group for Room Sharing or Trip Sharing.
    Has a generated passkey and configured member capacity (e.g. 3 members).
    """
    GROUP_TYPE_CHOICES = [
        ('room', 'Room Sharing'),
        ('trip', 'Trip Sharing'),
    ]
    group_type = models.CharField(max_length=20, choices=GROUP_TYPE_CHOICES, default='room')
    name = models.CharField(max_length=150, default='Room Sharing')
    passkey = models.CharField(max_length=30, unique=True, db_index=True)
    total_members = models.PositiveIntegerField(default=2)
    creator = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_sharing_groups')
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.get_group_type_display()} - {self.name} ({self.passkey})"

    @property
    def current_members_count(self):
        return self.memberships.count()

    @property
    def is_full(self):
        return self.current_members_count >= self.total_members


class SharingGroupMembership(models.Model):
    """
    Links a user to a SharingGroup with a role ('creator' or 'member').
    """
    group = models.ForeignKey(SharingGroup, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sharing_memberships')
    joined_at = models.DateTimeField(auto_now_add=True)
    role = models.CharField(max_length=20, default='member')

    class Meta:
        unique_together = ('group', 'user')
        ordering = ['joined_at']

    def __str__(self):
        return f"{self.user.username} in {self.group.name}"


class SharedExpense(models.Model):
    """
    Represents an expense entered in a SharingGroup (Room or Trip).
    Paid by one roommate, and split among selected group members (e.g. all 3, or AB, AC, BC, only A, etc.).
    """
    group = models.ForeignKey(SharingGroup, on_delete=models.CASCADE, related_name='expenses')
    paid_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='paid_shared_expenses')
    date = models.DateField(default=datetime.date.today)
    description = models.CharField(max_length=255, help_text="e.g. Gas bill, DSL Mall Dmart, KFC")
    category = models.CharField(max_length=100, default='Food', help_text="e.g. Rent, Groceries, Food, Travel, Utilities, Gas")
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    split_members = models.ManyToManyField(User, related_name='split_shared_expenses', blank=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_shared_expenses')
    created_at = models.DateTimeField(auto_now_add=True)
    is_settled = models.BooleanField(default=False, help_text="True if this expense has been settled/cleared between roommates.")
    settled_at = models.DateTimeField(null=True, blank=True)
    settled_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='settled_shared_expenses')

    class Meta:
        ordering = ['-date', '-id']
        indexes = [
            models.Index(fields=['group', 'date'], name='se_group_date_idx'),
            models.Index(fields=['group', 'is_settled'], name='se_group_settled_idx'),
        ]

    def __str__(self):
        return f"[{self.group.name}] {self.date} - {self.description} (₹{self.amount})"

    @property
    def per_person_share(self):
        count = self.split_members.count()
        if count > 0:
            return (self.amount / Decimal(count)).quantize(Decimal('0.01'))
        return self.amount

    @property
    def split_summary(self):
        count = self.split_members.count()
        total_in_group = self.group.total_members
        if count == total_in_group:
            return "All Members"
        elif count == 1:
            member = self.split_members.first()
            return f"Only {member.profile.display_name if hasattr(member, 'profile') else member.username}"
        else:
            names = [m.profile.display_name if hasattr(m, 'profile') else m.username for m in self.split_members.all()]
            return ", ".join(names)


class LoanRecord(models.Model):
    """
    Tracks money given to someone (lent) or taken from someone (borrowed).
    Supports optional simple interest calculation (per month or per year),
    duration in months or years, expected return date, and settlement status.
    """
    TYPE_CHOICES = [
        ('given', 'Given to Others (Money Lent / I Gave)'),
        ('taken', 'Taken from Others (Money Borrowed / I Took)'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending (Active)'),
        ('settled', 'Settled (Cleared / Returned)'),
    ]
    RATE_PERIOD_CHOICES = [
        ('month', 'Per Month'),
        ('year', 'Per Year (Per Annum)'),
    ]
    DURATION_UNIT_CHOICES = [
        ('months', 'Months'),
        ('years', 'Years'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='loan_records')
    transaction_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default='given')
    person_name = models.CharField(max_length=150, help_text="Name of the person")
    phone = models.CharField(max_length=20, blank=True, null=True, help_text="Optional phone number")
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))], help_text="Principal amount")
    given_date = models.DateField(default=datetime.date.today, help_text="Date money was given / taken")
    expected_return_date = models.DateField(blank=True, null=True, help_text="Expected repayment date")

    # Interest details
    has_interest = models.BooleanField(default=False, help_text="Whether interest is charged/payable")
    interest_rate = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('0.00'), help_text="Interest percentage")
    interest_period = models.CharField(max_length=10, choices=RATE_PERIOD_CHOICES, default='month', help_text="'month' or 'year'")
    duration_value = models.PositiveIntegerField(default=1, help_text="Duration count (e.g. 6)")
    duration_unit = models.CharField(max_length=10, choices=DURATION_UNIT_CHOICES, default='months', help_text="'months' or 'years'")

    notes = models.TextField(blank=True, help_text="Optional description / reason")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    settled_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-given_date', '-id']
        indexes = [
            models.Index(fields=['user', 'transaction_type', 'status'], name='lr_user_type_status_idx'),
        ]

    def __str__(self):
        type_str = "Gave" if self.transaction_type == 'given' else "Took"
        return f"{type_str} ₹{self.amount} - {self.person_name} ({self.status})"

    @property
    def duration_in_months(self):
        if self.duration_unit == 'years':
            return self.duration_value * 12
        return self.duration_value

    @property
    def duration_in_years(self):
        if self.duration_unit == 'years':
            return Decimal(self.duration_value)
        return (Decimal(self.duration_value) / Decimal('12.0'))

    @property
    def calculated_interest(self):
        if not self.has_interest or self.interest_rate <= Decimal('0.00') or self.duration_value <= 0:
            return Decimal('0.00')

        rate_fraction = self.interest_rate / Decimal('100.0')

        if self.interest_period == 'month':
            months = Decimal(self.duration_in_months)
            total_interest = self.amount * rate_fraction * months
            return total_interest.quantize(Decimal('0.01'))
        else:
            years = self.duration_in_years
            total_interest = self.amount * rate_fraction * years
            return total_interest.quantize(Decimal('0.01'))

    @property
    def total_expected_amount(self):
        return (self.amount + self.calculated_interest).quantize(Decimal('0.01'))

    @property
    def interest_description(self):
        if not self.has_interest:
            return "No Interest"
        period_str = "month" if self.interest_period == 'month' else "yr"
        return f"{self.interest_rate}%/{period_str} ({self.duration_value} {self.duration_unit}) → +₹{self.calculated_interest:,.2f}"


class Notification(models.Model):
    """
    Internal activity notifications for Sharing Group actions (bill added, edited,
    deleted, subgroup settled/reopened, or new roommate joined) so members logged
    in later immediately see missed activity and can click through to the exact item.
    """
    ACTION_CHOICES = [
        ('added', 'Bill Added'),
        ('edited', 'Bill Edited'),
        ('deleted', 'Bill Deleted'),
        ('settled', 'Balances Settled'),
        ('reopened', 'Balances Reopened'),
        ('joined', 'Member Joined'),
    ]

    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='acted_notifications')
    group = models.ForeignKey(SharingGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name='notifications')
    action_type = models.CharField(max_length=20, choices=ACTION_CHOICES, default='added')
    message = models.CharField(max_length=300)
    target_url = models.CharField(max_length=300, default='/room-tracker/')
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['recipient', 'is_read', '-created_at'], name='notif_recip_read_idx'),
        ]

    def __str__(self):
        return f"To {self.recipient.username}: {self.message} ({'Read' if self.is_read else 'Unread'})"

    @property
    def action_icon(self):
        icons = {
            'added': '➕',
            'edited': '✏️',
            'deleted': '🗑️',
            'settled': '🤝',
            'reopened': '↺',
            'joined': '👋',
        }
        return icons.get(self.action_type, '🔔')
