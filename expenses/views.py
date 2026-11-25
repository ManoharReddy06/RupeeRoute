DEFAULT_CATEGORIES = [
    'Food',
    'Food/Curd',
    'Travel',
    'Rent',
    'Shopping',
    'Recharge',
    'Entertainment',
    'Other'
]

import datetime
import calendar
import json
import random
import string
from decimal import Decimal, InvalidOperation
from collections import defaultdict
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.urls import reverse
from django.core.serializers.json import DjangoJSONEncoder
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum
from django.utils import timezone
from .models import UserProfile, PersonalExpense, SharingGroup, SharingGroupMembership, SharedExpense, LoanRecord, Notification
from .forms import LoginForm, RegisterForm, ProfileSetupForm, PersonalExpenseForm, CreateViewerForm
from .pdf_export import build_pdf_response, format_inr


def _actor_display_name(user):
    """Returns display name for an actor user."""
    if hasattr(user, 'profile') and user.profile.display_name:
        return user.profile.display_name
    return user.username


def _notify_group_members(group, actor, action_type, message, target_url):
    """Creates unread internal notifications for all other members in the sharing group."""
    other_member_ids = list(
        group.memberships.exclude(user=actor).values_list('user_id', flat=True)
    )
    if not other_member_ids:
        return
    Notification.objects.bulk_create([
        Notification(
            recipient_id=uid,
            actor=actor,
            group=group,
            action_type=action_type,
            message=message[:300],
            target_url=target_url[:300],
            is_read=False,
        )
        for uid in other_member_ids
    ])


ANALYTICS_PIE_PALETTE = [
    '#4f46e5',  # Indigo
    '#0ea5e9',  # Sky Blue
    '#10b981',  # Emerald
    '#f59e0b',  # Amber
    '#ec4899',  # Pink
    '#8b5cf6',  # Violet
    '#06b6d4',  # Cyan
    '#ef4444',  # Red
    '#14b8a6',  # Teal
    '#f97316',  # Orange
    '#6366f1',  # Light Indigo
    '#84cc16',  # Lime
]


def _resolve_target_user(request):
    """Resolves viewer mode to owner user/profile when logged in as a viewer."""
    user_profile, _ = UserProfile.objects.get_or_create(user=request.user)
    is_viewer = bool(user_profile.is_viewer and user_profile.viewer_of)
    if is_viewer:
        target_user = user_profile.viewer_of
        target_profile, _ = UserProfile.objects.get_or_create(user=target_user)
    else:
        is_viewer = bool(user_profile.is_viewer)
        target_user = request.user
        target_profile = user_profile
    return is_viewer, target_user, target_profile, user_profile


def _parse_month_year_params(request, today=None):
    """Parses month/year query filters uniformly across dashboard, sharing, analytics, and exports."""
    today = today or datetime.date.today()
    try:
        selected_year = int(request.GET.get('year', today.year))
    except (ValueError, TypeError):
        selected_year = today.year

    month_param = request.GET.get('month')
    if month_param in ['0', 'all', 'yearly']:
        is_full_year = True
        selected_month = 0
        month_name = "Full Year"
    else:
        is_full_year = False
        try:
            selected_month = int(month_param or today.month)
        except (ValueError, TypeError):
            selected_month = today.month

        if selected_month < 1 or selected_month > 12:
            selected_month = today.month

        try:
            month_name = datetime.date(selected_year, selected_month, 1).strftime('%B')
        except Exception:
            month_name = f"Month {selected_month}"

    months_list = [
        (0, '🌟 All Months (Full Year)'),
        (1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'),
        (5, 'May'), (6, 'June'), (7, 'July'), (8, 'August'),
        (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December')
    ]
    years_list = [today.year - 2, today.year - 1, today.year, today.year + 1]
    return {
        'selected_year': selected_year,
        'selected_month': selected_month,
        'is_full_year': is_full_year,
        'month_name': month_name,
        'months_list': months_list,
        'years_list': years_list,
    }


def _get_personal_unified_expenses(target_user, selected_year):
    """Returns sorted list of PersonalExpense + user's SharedExpense fair shares for a year."""
    personal_year_qs = list(PersonalExpense.objects.filter(
        user=target_user,
        date__year=selected_year
    ).order_by('-date', '-id'))
    for pe in personal_year_qs:
        pe.is_shared = False

    shared_year_qs = list(SharedExpense.objects.filter(
        split_members=target_user,
        date__year=selected_year,
        group__is_active=True
    ).select_related('paid_by', 'paid_by__profile', 'group').prefetch_related('split_members').order_by('-date', '-id'))

    shared_items = []
    for se in shared_year_qs:
        share_amt = se.per_person_share
        payer_name = se.paid_by.profile.display_name if hasattr(se.paid_by, 'profile') else se.paid_by.username
        shared_items.append(UnifiedExpenseItem(
            id=f"shared_{se.id}",
            date=se.date,
            description=se.description,
            category=se.category,
            amount=share_amt,
            is_shared=True,
            shared_total_bill=se.amount,
            shared_paid_by=payer_name,
            group_name=se.group.name,
            group_type=se.group.group_type
        ))

    return sorted(personal_year_qs + shared_items, key=lambda x: (x.date, str(getattr(x, 'id', 0))), reverse=True)


def _build_pie_slices(category_totals_dict, palette=None):
    """Builds JSON-friendly sorted pie slice dicts with percentages and colors."""
    colors_list = palette or ANALYTICS_PIE_PALETTE
    total = sum((Decimal(v) for v in category_totals_dict.values()), Decimal('0.00'))
    sorted_items = sorted(
        [(k, Decimal(v)) for k, v in category_totals_dict.items() if Decimal(v) > Decimal('0.00')],
        key=lambda x: x[1],
        reverse=True
    )
    slices = []
    for idx, (label, amt) in enumerate(sorted_items):
        pct = float(round((amt / total) * Decimal('100.0'), 1)) if total > Decimal('0.00') else 0.0
        slices.append({
            'name': label,
            'amount': float(amt),
            'amount_formatted': f"₹{amt:,.2f}",
            'percentage': pct,
            'color': colors_list[idx % len(colors_list)],
        })
    return total, slices


def login_view(request):
    """
    User login view with username & password.
    Redirects to Analytics landing page upon login.
    """
    if request.user.is_authenticated:
        return redirect('analytics')

    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username'].strip()
            password = form.cleaned_data['password']
            if '@' in username:
                user_match = User.objects.filter(email__iexact=username).first()
                if user_match:
                    username = user_match.username
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                next_url = request.GET.get('next') or 'analytics'
                return redirect(next_url)
            else:
                messages.error(request, "Invalid username or password. Please try again.")
    else:
        form = LoginForm()

    return render(request, 'expenses/login.html', {'form': form})


def register_view(request):
    """
    User registration view.
    """
    if request.user.is_authenticated:
        return redirect('analytics')

    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            email = form.cleaned_data.get('email', '')
            password = form.cleaned_data['password']

            user = User.objects.create_user(
                username=username,
                email=email,
                password=password
            )

            # Initialize UserProfile (ready for profile setup)
            UserProfile.objects.create(user=user, is_profile_setup=False)

            login(request, user)
            messages.success(request, f"Welcome, {username}! Please set up your profile to start tracking.")
            return redirect('home')
    else:
        form = RegisterForm()

    return render(request, 'expenses/register.html', {'form': form})


def logout_view(request):
    """
    User logout view.
    """
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect('login')


class UnifiedExpenseItem:
    """
    Represents a unified expense item for Personal Tracker combining personal
    expenses with the user's individual fair share of room/trip shared expenses.
    """
    def __init__(self, id, date, description, category, amount, is_shared=False, shared_total_bill=Decimal('0.00'), shared_paid_by='', group_name='', group_type='room'):
        self.id = id
        self.date = date
        self.description = description
        self.category = category
        self.amount = amount
        self.is_shared = is_shared
        self.shared_total_bill = shared_total_bill
        self.shared_paid_by = shared_paid_by
        self.group_name = group_name
        self.group_type = group_type


@login_required
def home_view(request):
    """
    Main entry point:
    - If user profile is not set up, shows Profile Setup dashboard.
    - If user profile is set up, shows Personal Tracker Dashboard with:
      - Month & Year selector at the top
      - Profile card (avatar, name, age, current month expense)
      - Category breakdown tab
      - Past entries history table with 'Enter New Spents' button
    """
    is_viewer, target_user, target_profile, profile = _resolve_target_user(request)

    # 1. First-time Profile Setup Check (only for owner/admin accounts)
    if not is_viewer and not target_profile.is_profile_setup:
        if request.method == 'POST':
            setup_form = ProfileSetupForm(request.POST, request.FILES, instance=profile)
            if setup_form.is_valid():
                p = setup_form.save(commit=False)
                p.is_profile_setup = True
                p.save()
                messages.success(request, "Profile setup complete! Welcome to RupeeRoute.")
                return redirect('home')
        else:
            setup_form = ProfileSetupForm(instance=profile)

        return render(request, 'expenses/profile_setup.html', {'form': setup_form})

    # 2. Month and Year Selection
    today = datetime.date.today()
    period = _parse_month_year_params(request, today)
    selected_year = period['selected_year']
    selected_month = period['selected_month']
    is_full_year = period['is_full_year']
    month_name = period['month_name']
    months_list = period['months_list']
    years_list = period['years_list']

    # Query unified personal + shared expenses for the selected year
    year_expenses = _get_personal_unified_expenses(target_user, selected_year)
    total_year_spent = sum(e.amount for e in year_expenses)
    year_expenses_count = len(year_expenses)

    # Filter for active period (either full year or specific month)
    if is_full_year:
        expenses = year_expenses
        total_period_spent = total_year_spent
        period_label = f"Full Year {selected_year}"
        # For the month card preview, default to current month or latest month in that year
        target_preview_month = today.month if selected_year == today.year else 11
        month_expenses = [e for e in year_expenses if e.date.month == target_preview_month]
        total_month_spent = sum(e.amount for e in month_expenses)
        month_expenses_count = len(month_expenses)
        preview_month_name = datetime.date(selected_year, target_preview_month, 1).strftime('%B')
    else:
        month_expenses = [e for e in year_expenses if e.date.month == selected_month]
        expenses = month_expenses
        total_month_spent = sum(e.amount for e in month_expenses)
        total_period_spent = total_month_spent
        month_expenses_count = len(month_expenses)
        period_label = f"{month_name} {selected_year}"
        preview_month_name = month_name

    # 4. Calculate Category Breakdown for the active view period
    category_totals = defaultdict(Decimal)
    category_counts = defaultdict(int)
    category_expenses = defaultdict(list)

    for exp in expenses:
        cat_name = exp.category.strip() if exp.category else 'Other'
        category_totals[cat_name] += exp.amount
        category_counts[cat_name] += 1
        category_expenses[cat_name].append(exp)

    category_breakdown = []
    category_breakdown_serializable = []
    for cat_name, amt in category_totals.items():
        pct = (amt / total_period_spent * Decimal('100.0')) if total_period_spent > Decimal('0.00') else Decimal('0.00')
        category_breakdown.append({
            'name': cat_name,
            'amount': amt,
            'percentage': round(pct, 1),
            'count': category_counts[cat_name],
            'expenses': category_expenses[cat_name],
        })

        items_list = []
        for item in category_expenses[cat_name]:
            is_item_shared = getattr(item, 'is_shared', False)
            desc_text = item.description + (f" [👥 {item.group_name} Share]" if is_item_shared else "")
            del_url = reverse('delete_expense', kwargs={'expense_id': item.id}) if not is_item_shared else ""
            items_list.append({
                'id': item.id,
                'date': item.date.strftime('%d/%m/%Y'),
                'raw_date': item.date.strftime('%Y-%m-%d'),
                'category': item.category,
                'description': desc_text,
                'amount': f"{item.amount:.2f}",
                'is_shared': is_item_shared,
                'delete_url': del_url,
            })

        category_breakdown_serializable.append({
            'name': cat_name,
            'amount': f"{amt:.2f}",
            'percentage': float(round(pct, 1)),
            'count': category_counts[cat_name],
            'items': items_list,
        })

    # Sort categories descending by amount
    category_breakdown.sort(key=lambda x: x['amount'], reverse=True)
    category_breakdown_serializable.sort(key=lambda x: float(x['amount']), reverse=True)
    category_breakdown_json = json.dumps(category_breakdown_serializable, cls=DjangoJSONEncoder)

    # 5. Optional filters from URL parameters (Category, Date, Amount)
    selected_category = request.GET.get('category', '').strip()
    filter_date = request.GET.get('date', '').strip()
    min_amount_param = request.GET.get('min_amount', '').strip()
    max_amount_param = request.GET.get('max_amount', '').strip()

    display_expenses = expenses
    if selected_category:
        display_expenses = [e for e in display_expenses if e.category.strip().lower() == selected_category.lower()]
    if filter_date:
        try:
            parsed_d = datetime.date.fromisoformat(filter_date)
            display_expenses = [e for e in display_expenses if e.date == parsed_d]
        except ValueError:
            pass
    if min_amount_param:
        try:
            min_val = Decimal(min_amount_param)
            display_expenses = [e for e in display_expenses if e.amount >= min_val]
        except Exception:
            pass
    if max_amount_param:
        try:
            max_val = Decimal(max_amount_param)
            display_expenses = [e for e in display_expenses if e.amount <= max_val]
        except Exception:
            pass

    # Available categories for selection in Add and Edit modals
    user_distinct_cats = list(PersonalExpense.objects.filter(user=target_user).values_list('category', flat=True).distinct())
    available_categories = list(DEFAULT_CATEGORIES)
    for c in user_distinct_cats:
        c_clean = (c or '').strip()
        if c_clean and c_clean not in available_categories:
            available_categories.append(c_clean)

    # 6. Form for Enter New Spents
    if not is_full_year and selected_year == today.year and selected_month == today.month:
        default_form_date = today
    elif is_full_year:
        default_form_date = today if selected_year == today.year else datetime.date(selected_year, 1, 1)
    else:
        default_form_date = datetime.date(selected_year, selected_month, 1)

    initial_form_data = {'date': default_form_date}
    if selected_category:
        initial_form_data['category'] = selected_category

    expense_form = PersonalExpenseForm(initial=initial_form_data)

    context = {
        'profile': target_profile,
        'owner_user': target_user,
        'is_viewer': is_viewer,
        'selected_month': selected_month,
        'selected_year': selected_year,
        'selected_category': selected_category,
        'filter_date': filter_date,
        'min_amount_param': min_amount_param,
        'max_amount_param': max_amount_param,
        'is_full_year': is_full_year,
        'month_name': month_name,
        'preview_month_name': preview_month_name,
        'period_label': period_label,
        'months_list': months_list,
        'years_list': years_list,
        'total_period_spent': total_period_spent,
        'total_month_spent': total_month_spent,
        'month_expenses_count': month_expenses_count,
        'total_year_spent': total_year_spent,
        'year_expenses_count': year_expenses_count,
        'category_breakdown': category_breakdown,
        'category_breakdown_json': category_breakdown_json,
        'expenses': display_expenses,
        'all_expenses': expenses,
        'expense_form': expense_form,
        'available_categories': available_categories,
        'current_tracker': 'personal',
    }
    return render(request, 'expenses/dashboard.html', context)


def _build_monthly_installments(base_date, total_amount, split_months):
    """Computes (target_date, month_amount, desc_suffix) installments across future months."""
    amount_per_month = (total_amount / Decimal(split_months)).quantize(Decimal('0.01'))
    total_allocated = Decimal('0.00')
    installments = []
    for i in range(split_months):
        month_offset = base_date.month - 1 + i
        target_year = base_date.year + (month_offset // 12)
        target_month = (month_offset % 12) + 1
        max_days = calendar.monthrange(target_year, target_month)[1]
        target_day = min(base_date.day, max_days)
        target_date = datetime.date(target_year, target_month, target_day)

        if i == split_months - 1:
            month_amount = total_amount - total_allocated
        else:
            month_amount = amount_per_month
            total_allocated += month_amount

        month_abbr = target_date.strftime('%b')
        desc_suffix = f" (Split {i+1}/{split_months} - {month_abbr})"
        installments.append((target_date, month_amount, desc_suffix))
    return installments


@login_required
def add_expense_view(request):
    """
    Handles submitting a new spent entry:
    - Date, Description, Category, Amount
    - Optional split across multiple months (e.g. Gym fee for 3 months)
    - Recalculates both Top Profile Card and Expense Breakdown immediately!
    """
    if hasattr(request.user, 'profile') and request.user.profile.is_viewer:
        messages.error(request, "Viewers have read-only access and cannot add expenses.")
        return redirect('home')

    if request.method == 'POST':
        form = PersonalExpenseForm(request.POST)
        if form.is_valid():
            is_split = request.POST.get('is_split') == 'true'
            split_months_raw = request.POST.get('split_months', '1')
            try:
                split_months = max(1, min(24, int(split_months_raw))) if is_split else 1
            except (ValueError, TypeError):
                split_months = 1

            base_expense = form.save(commit=False)
            base_expense.user = request.user
            total_amount = base_expense.amount
            base_date = base_expense.date
            base_desc = base_expense.description
            category = base_expense.category

            if is_split and split_months > 1 and total_amount > Decimal('0.00'):
                installments = _build_monthly_installments(base_date, total_amount, split_months)
                created_entries = [
                    PersonalExpense.objects.create(
                        user=request.user,
                        date=t_date,
                        category=category,
                        amount=m_amt,
                        description=f"{base_desc}{suffix}"
                    )
                    for t_date, m_amt, suffix in installments
                ]

                first_month_str = base_date.strftime('%b %Y')
                last_month_str = created_entries[-1].date.strftime('%b %Y')
                messages.success(
                    request,
                    f"Added '₹{total_amount} - {base_desc}' split into {split_months} monthly installments ({first_month_str} to {last_month_str})!"
                )
                return redirect(f"/?month={base_date.month}&year={base_date.year}")
            else:
                base_expense.save()
                messages.success(request, f"Added '₹{base_expense.amount} - {base_expense.description}' successfully!")
                # Redirect back to the exact month and year of the added expense
                return redirect(f"/?month={base_expense.date.month}&year={base_expense.date.year}")
        else:
            messages.error(request, "Please enter valid expense details.")

    return redirect('home')


@login_required
def edit_expense_view(request, expense_id):
    """
    Handles editing an existing spent entry:
    - Pre-filled with existing details
    - Recalculates both Top Profile Card and Expense Breakdown immediately!
    """
    if hasattr(request.user, 'profile') and request.user.profile.is_viewer:
        messages.error(request, "Viewers have read-only access and cannot edit expenses.")
        return redirect('home')

    expense = get_object_or_404(PersonalExpense, id=expense_id, user=request.user)

    if request.method == 'POST':
        form = PersonalExpenseForm(request.POST, instance=expense)
        if form.is_valid():
            updated_expense = form.save()
            messages.success(request, f"Updated '₹{updated_expense.amount} - {updated_expense.description}' successfully!")
            return redirect(f"/?month={updated_expense.date.month}&year={updated_expense.date.year}")
        else:
            messages.error(request, "Please enter valid expense details.")
            return redirect(f"/?month={expense.date.month}&year={expense.date.year}")

    return redirect('home')


@login_required
def delete_expense_view(request, expense_id):
    """
    Deletes an existing spent entry and recalculates totals.
    """
    if hasattr(request.user, 'profile') and request.user.profile.is_viewer:
        messages.error(request, "Viewers have read-only access and cannot delete expenses.")
        return redirect('home')

    expense = get_object_or_404(PersonalExpense, id=expense_id, user=request.user)
    m = expense.date.month
    y = expense.date.year
    if request.method == 'POST':
        desc = expense.description
        amt = expense.amount
        expense.delete()
        messages.success(request, f"Deleted '₹{amt} - {desc}'.")

    return redirect(f"/?month={m}&year={y}")


def generate_sharing_passkey(prefix='ROOM'):
    """
    Generates a unique, easy-to-share passkey (e.g. ROOM-4921 or TRIP-7182).
    """
    prefix = prefix.upper()
    while True:
        num = ''.join(random.choices(string.digits, k=4))
        code = f"{prefix}-{num}"
        if not SharingGroup.objects.filter(passkey__iexact=code).exists():
            return code


def get_member_stats(member_user, today=None, selected_year=None, selected_month=None):
    """
    Computes Monthly Spent (for selected month/year) and Monthly Average (lifetime average across active months).
    """
    if today is None:
        today = datetime.date.today()

    year_val = selected_year if selected_year is not None else today.year
    month_val = selected_month if selected_month is not None else today.month

    # Monthly Spent for current/selected month
    if month_val > 0:
        month_spent = PersonalExpense.objects.filter(
            user=member_user,
            date__year=year_val,
            date__month=month_val
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    else:
        month_spent = PersonalExpense.objects.filter(
            user=member_user,
            date__year=year_val
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    # Monthly Average: lifetime total / number of distinct active months
    distinct_months = PersonalExpense.objects.filter(
        user=member_user
    ).values('date__year', 'date__month').distinct().count()

    lifetime_total = PersonalExpense.objects.filter(
        user=member_user
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    if distinct_months > 0:
        monthly_avg = (lifetime_total / Decimal(distinct_months)).quantize(Decimal('0.01'))
    else:
        monthly_avg = month_spent

    profile = getattr(member_user, 'profile', None)

    return {
        'user': member_user,
        'profile': profile,
        'display_name': profile.display_name if profile else member_user.username,
        'initials': profile.initials if profile else (member_user.username[:2].upper() if member_user.username else 'ME'),
        'avatar': profile.avatar if profile else None,
        'age': profile.age if profile else None,
        'monthly_spent': month_spent,
        'monthly_average': monthly_avg,
    }


def build_group_context(group, request_user, today, selected_year=None, selected_month=None):
    """
    Builds the joined member cards, remaining empty waiting slots up to group.total_members,
    category breakdown, shared expense history, and per-member balances filtered by month & year.
    The logged-in user (request_user) is ALWAYS positioned 1st in the list, followed by other members.
    """
    all_memberships = list(group.memberships.select_related('user', 'user__profile').all())

    # Current user's membership is placed first so their profile card displays 1st
    current_user_m = [m for m in all_memberships if m.user == request_user]
    other_memberships = [m for m in all_memberships if m.user != request_user]
    ordered_memberships = current_user_m + other_memberships

    # Fetch shared expenses for this group filtered by selected month and year
    shared_qs = group.expenses.select_related('paid_by', 'paid_by__profile', 'created_by').prefetch_related('split_members', 'split_members__profile').order_by('-date', '-id')

    if selected_year:
        shared_qs = shared_qs.filter(date__year=selected_year)
    if selected_month is not None and selected_month > 0:
        shared_qs = shared_qs.filter(date__month=selected_month)

    shared_expenses_qs = list(shared_qs)

    has_shared_bills = len(shared_expenses_qs) > 0
    total_group_spent = sum((e.amount for e in shared_expenses_qs), Decimal('0.00'))

    # Calculate per-member totals in this group
    member_paid_map = defaultdict(lambda: Decimal('0.00'))
    member_share_map = defaultdict(lambda: Decimal('0.00'))
    member_unsettled_paid_map = defaultdict(lambda: Decimal('0.00'))
    member_unsettled_share_map = defaultdict(lambda: Decimal('0.00'))

    for exp in shared_expenses_qs:
        member_paid_map[exp.paid_by_id] += exp.amount
        splits = list(exp.split_members.all())
        if splits:
            per_head = (exp.amount / Decimal(len(splits))).quantize(Decimal('0.01'))
            for sm in splits:
                member_share_map[sm.id] += per_head

            if not exp.is_settled:
                member_unsettled_paid_map[exp.paid_by_id] += exp.amount
                for sm in splits:
                    member_unsettled_share_map[sm.id] += per_head

    members_list = []
    for idx, m in enumerate(ordered_memberships, start=1):
        stats = get_member_stats(m.user, today, selected_year, selected_month)
        stats['is_current_user'] = (m.user == request_user)
        stats['is_creator'] = (m.user == group.creator)
        stats['role'] = m.role
        stats['slot_number'] = idx

        if has_shared_bills:
            paid = member_paid_map[m.user.id]
            share = member_share_map[m.user.id]
            # Active net balance is calculated from unsettled expenses
            balance = member_unsettled_paid_map[m.user.id] - member_unsettled_share_map[m.user.id]

            stats['monthly_spent'] = paid
            stats['monthly_average'] = share
            stats['balance'] = balance
            if balance > Decimal('0.005'):
                stats['balance_status'] = 'extra'
                stats['balance_amount'] = balance.quantize(Decimal('0.01'))
                stats['balance_label'] = f"+₹{balance:,.2f} Extra (Gets back)"
            elif balance < Decimal('-0.005'):
                stats['balance_status'] = 'short'
                stats['balance_amount'] = abs(balance).quantize(Decimal('0.01'))
                stats['balance_label'] = f"-₹{abs(balance):,.2f} Short (Owes)"
            else:
                stats['balance_status'] = 'settled'
                stats['balance_amount'] = Decimal('0.00')
                stats['balance_label'] = "✓ ₹0.00 Settled"
        else:
            stats['balance'] = Decimal('0.00')
            stats['balance_status'] = 'settled'
            stats['balance_amount'] = Decimal('0.00')
            stats['balance_label'] = "✓ ₹0.00 Settled"

        members_list.append(stats)

    # Calculate empty waiting slots
    empty_slots = []
    for slot_num in range(len(members_list) + 1, group.total_members + 1):
        empty_slots.append({
            'slot_number': slot_num,
        })

    # Category breakdown for this group
    CATEGORY_ICONS = {
        'food': '🍔',
        'food & dining': '🍔',
        'food/curd': '🥛',
        'groceries': '🛒',
        'rent': '🏠',
        'rent & housing': '🏠',
        'travel': '🚕',
        'travel & commute': '🚕',
        'utilities': '💡',
        'utilities & bills': '💡',
        'gas': '⛽',
        'gas & fuel': '⛽',
        'shopping': '🛍️',
        'entertainment': '🎬',
        'medical & health': '💊',
        'recharge': '📱',
        'other': '🏷️',
    }

    cat_totals = defaultdict(lambda: {'amount': Decimal('0.00'), 'count': 0})
    for exp in shared_expenses_qs:
        cat_key = exp.category.strip()
        cat_totals[cat_key]['amount'] += exp.amount
        cat_totals[cat_key]['count'] += 1

    category_breakdown = []
    for cat_name, data in sorted(cat_totals.items(), key=lambda item: item[1]['amount'], reverse=True):
        amt = data['amount']
        pct = (amt / total_group_spent * 100).quantize(Decimal('0.1')) if total_group_spent > 0 else Decimal('0.0')
        icon = CATEGORY_ICONS.get(cat_name.lower(), '🏷️')
        category_breakdown.append({
            'name': cat_name,
            'amount': amt,
            'count': data['count'],
            'percentage': pct,
            'icon': icon,
        })

    # Expenses history list
    expenses_history = []
    for exp in shared_expenses_qs:
        splits = list(exp.split_members.all())
        split_count = len(splits)
        per_head = (exp.amount / Decimal(split_count)).quantize(Decimal('0.01')) if split_count > 0 else exp.amount

        split_names = [s.profile.display_name if hasattr(s, 'profile') else s.username for s in splits]
        if split_count == group.total_members:
            split_desc = "All Members"
        elif split_count == 1:
            split_desc = f"Only {split_names[0]}"
        else:
            split_desc = ", ".join(split_names)

        payer_name = exp.paid_by.profile.display_name if hasattr(exp.paid_by, 'profile') else exp.paid_by.username
        payer_initials = exp.paid_by.profile.initials if hasattr(exp.paid_by, 'profile') else exp.paid_by.username[:2].upper()
        payer_avatar = exp.paid_by.profile.avatar.url if (hasattr(exp.paid_by, 'profile') and exp.paid_by.profile.avatar) else None

        split_ids = [s.id for s in splits]
        can_edit = (request_user.id == exp.created_by_id or request_user.id == exp.paid_by_id)
        can_delete = can_edit

        expenses_history.append({
            'id': exp.id,
            'date': exp.date,
            'description': exp.description,
            'category': exp.category,
            'category_icon': CATEGORY_ICONS.get(exp.category.lower(), '🏷️'),
            'amount': exp.amount,
            'paid_by_id': exp.paid_by_id,
            'paid_by_name': payer_name,
            'paid_by_initials': payer_initials,
            'paid_by_avatar': payer_avatar,
            'is_paid_by_current_user': (exp.paid_by_id == request_user.id),
            'split_count': split_count,
            'split_names': split_names,
            'split_desc': split_desc,
            'split_ids': split_ids,
            'split_ids_json': json.dumps(split_ids),
            'per_head': per_head,
            'is_settled': exp.is_settled,
            'can_edit': can_edit,
            'can_delete': can_delete,
        })

    available_categories = [
        'Food & Dining',
        'Groceries',
        'Rent & Housing',
        'Travel & Commute',
        'Utilities & Bills',
        'Gas & Fuel',
        'Entertainment',
        'Shopping',
        'Other'
    ]

    # Include any custom categories already entered in group bills
    for exp in shared_expenses_qs:
        if exp.category and exp.category.strip() and exp.category.strip() not in available_categories:
            available_categories.append(exp.category.strip())

    # -------------------------------------------------------------------------
    # Scenario / Subgroup Split Breakdown (e.g. ABC, AB, AC, BC)
    # -------------------------------------------------------------------------
    all_members_dict = {m.user.id: m.user for m in all_memberships}
    user_letter_map = {}
    for i, m in enumerate(ordered_memberships):
        user_letter_map[m.user.id] = chr(65 + i) if i < 26 else f"M{i+1}"

    scenario_map = defaultdict(list)
    for exp in shared_expenses_qs:
        splits = list(exp.split_members.all())
        if not splits:
            splits = [m.user for m in all_memberships]
        split_key = tuple(sorted([s.id for s in splits]))
        scenario_map[split_key].append(exp)

    sorted_scenario_keys = sorted(scenario_map.keys(), key=lambda k: (-len(k), k))

    scenario_breakdowns = []
    for split_key in sorted_scenario_keys:
        exp_list = scenario_map[split_key]
        participant_count = len(split_key)
        subtotal = sum((e.amount for e in exp_list), Decimal('0.00'))
        fair_share = (subtotal / Decimal(participant_count)).quantize(Decimal('0.01')) if participant_count > 0 else Decimal('0.00')

        code_letters = "".join([user_letter_map.get(uid, "?") for uid in split_key])

        # Check if this subgroup scenario is already settled
        is_fully_settled = all(e.is_settled for e in exp_list) if exp_list else False
        unsettled_exp_list = [e for e in exp_list if not e.is_settled]
        unsettled_subtotal = sum((e.amount for e in unsettled_exp_list), Decimal('0.00'))
        unsettled_fair_share = (unsettled_subtotal / Decimal(participant_count)).quantize(Decimal('0.01')) if participant_count > 0 else Decimal('0.00')

        participants_data = []
        debtors = []
        creditors = []

        for uid in split_key:
            u = all_members_dict.get(uid)
            uname = u.profile.display_name if (u and hasattr(u, 'profile') and u.profile.display_name) else (u.username if u else f"User {uid}")
            u_initials = u.profile.initials if (u and hasattr(u, 'profile') and u.profile.initials) else uname[:2].upper()
            letter = user_letter_map.get(uid, "")

            total_paid_amt = sum((e.amount for e in exp_list if e.paid_by_id == uid), Decimal('0.00'))

            if is_fully_settled:
                bal = Decimal('0.00')
                bal_status = 'settled'
                bal_label = "✓ ₹0.00 Cleared"
            else:
                paid_unsettled = sum((e.amount for e in unsettled_exp_list if e.paid_by_id == uid), Decimal('0.00'))
                bal = paid_unsettled - unsettled_fair_share

                if bal > Decimal('0.005'):
                    bal_status = 'extra'
                    bal_label = f"+₹{bal:,.2f}"
                    creditors.append({'name': uname, 'letter': letter, 'amount': bal})
                elif bal < Decimal('-0.005'):
                    bal_status = 'short'
                    bal_label = f"-₹{abs(bal):,.2f}"
                    debtors.append({'name': uname, 'letter': letter, 'amount': abs(bal)})
                else:
                    bal_status = 'settled'
                    bal_label = "₹0.00"

            participants_data.append({
                'user_id': uid,
                'name': uname,
                'initials': u_initials,
                'letter': letter,
                'is_current_user': (uid == request_user.id),
                'paid': total_paid_amt,
                'average': fair_share,
                'balance': bal,
                'balance_status': bal_status,
                'balance_label': bal_label,
            })

        # Calculate settlement instructions (who pays whom to clear differences)
        settlement_instructions = []
        if not is_fully_settled and debtors and creditors:
            d_list = [{'name': d['name'], 'letter': d['letter'], 'amt': d['amount']} for d in debtors]
            c_list = [{'name': c['name'], 'letter': c['letter'], 'amt': c['amount']} for c in creditors]
            d_idx = 0
            c_idx = 0

            while d_idx < len(d_list) and c_idx < len(c_list):
                d_item = d_list[d_idx]
                c_item = c_list[c_idx]
                settle_amt = min(d_item['amt'], c_item['amt'])

                if settle_amt > Decimal('0.005'):
                    settlement_instructions.append(
                        f"{d_item['name']} ({d_item['letter']}) pays {c_item['name']} ({c_item['letter']}) ₹{settle_amt:,.2f}"
                    )

                d_item['amt'] -= settle_amt
                c_item['amt'] -= settle_amt

                if d_item['amt'] <= Decimal('0.005'):
                    d_idx += 1
                if c_item['amt'] <= Decimal('0.005'):
                    c_idx += 1

        scenario_breakdowns.append({
            'code': code_letters,
            'title': f"{code_letters}: " + " + ".join([p['name'] for p in participants_data]),
            'participant_ids': list(split_key),
            'participant_ids_json': json.dumps(list(split_key)),
            'participant_count': participant_count,
            'subtotal': subtotal,
            'fair_share': fair_share,
            'participants': participants_data,
            'bills_count': len(exp_list),
            'unsettled_bills_count': len(unsettled_exp_list),
            'is_settled': is_fully_settled,
            'settlement_instructions': settlement_instructions,
        })

    def serialize_scenario_breakdown(scenarios):
        serialized = []
        for s in scenarios:
            serialized.append({
                'code': s['code'],
                'title': s['title'],
                'participant_ids': s['participant_ids'],
                'participant_ids_json': s['participant_ids_json'],
                'participant_count': s['participant_count'],
                'subtotal': float(s['subtotal']),
                'fair_share': float(s['fair_share']),
                'participants': [{
                    'user_id': p['user_id'],
                    'name': p['name'],
                    'initials': p['initials'],
                    'letter': p['letter'],
                    'is_current_user': p['is_current_user'],
                    'paid': float(p['paid']),
                    'average': float(p['average']),
                    'balance': float(p['balance']),
                    'balance_status': p['balance_status'],
                    'balance_label': p['balance_label'],
                } for p in s['participants']],
                'bills_count': s['bills_count'],
                'unsettled_bills_count': s['unsettled_bills_count'],
                'is_settled': s['is_settled'],
                'settlement_instructions': s['settlement_instructions'],
            })
        return serialized

    def serialize_expenses_history(expenses):
        serialized = []
        for e in expenses:
            serialized.append({
                'id': e['id'],
                'date': e['date'].strftime('%d/%m/%Y'),
                'description': e['description'],
                'category': e['category'],
                'category_icon': e['category_icon'],
                'amount': float(e['amount']),
                'paid_by_id': e['paid_by_id'],
                'paid_by_name': e['paid_by_name'],
                'split_count': e['split_count'],
                'split_names': e['split_names'],
                'split_desc': e['split_desc'],
                'split_ids': e['split_ids'],
                'per_head': float(e['per_head']),
                'is_settled': e['is_settled'],
                'can_edit': e['can_edit'],
                'can_delete': e['can_delete'],
            })
        return serialized

    return {
        'group': group,
        'id': group.id,
        'passkey': group.passkey,
        'name': group.name,
        'group_type': group.group_type,
        'total_members': group.total_members,
        'current_members_count': len(members_list),
        'members': members_list,
        'empty_slots': empty_slots,
        'is_creator': (group.creator == request_user),
        'total_spent': total_group_spent,
        'has_shared_bills': has_shared_bills,
        'category_breakdown': category_breakdown,
        'expenses_history': expenses_history,
        'expenses_count': len(expenses_history),
        'available_categories': available_categories,
        'scenario_breakdowns': scenario_breakdowns,
        'scenario_breakdowns_json': json.dumps(serialize_scenario_breakdown(scenario_breakdowns)),
        'expenses_history_json': json.dumps(serialize_expenses_history(expenses_history)),
    }


@login_required
def room_tracker_view(request):
    """
    Sharing Hub view:
    - Default Landing Screen shows ONLY a Note and two centered buttons: Room Sharing & Trip Sharing.
    - Clicking Room Sharing opens Room internal page asking for existing passkey or create room.
    - After creating or joining with passkey, displays member profile cards.
    - Supports Month & Year filtering identical to Personal Tracker.
    - Viewer profile can view the admin/owner's Room and Trip Sharing groups in read-only mode!
    """
    today = datetime.date.today()
    user_profile, _ = UserProfile.objects.get_or_create(user=request.user)

    is_viewer = hasattr(request.user, 'profile') and request.user.profile.is_viewer
    if is_viewer and request.user.profile.viewer_of:
        target_user = request.user.profile.viewer_of
        target_profile = getattr(target_user, 'profile', user_profile)
    else:
        target_user = request.user
        target_profile = user_profile

    active_mode = request.GET.get('mode', '').strip().lower() or request.GET.get('toggle', '').strip().lower()

    # Month and Year selection
    try:
        selected_year = int(request.GET.get('year', today.year))
    except (ValueError, TypeError):
        selected_year = today.year

    month_param = request.GET.get('month')
    if month_param in ['0', 'all', 'yearly']:
        selected_month = 0
        month_name = "Full Year"
    else:
        try:
            selected_month = int(month_param or today.month)
        except (ValueError, TypeError):
            selected_month = today.month

        if selected_month < 1 or selected_month > 12:
            selected_month = today.month

        try:
            month_name = datetime.date(selected_year, selected_month, 1).strftime('%B')
        except Exception:
            month_name = f"Month {selected_month}"

    months_list = [
        (0, '🌟 All Months (Full Year)'),
        (1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'),
        (5, 'May'), (6, 'June'), (7, 'July'), (8, 'August'),
        (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December')
    ]
    years_list = [today.year - 2, today.year - 1, today.year, today.year + 1]

    # Room Sharing group (uses target_user so viewers see owner's room)
    room_membership = SharingGroupMembership.objects.filter(
        user=target_user,
        group__group_type='room',
        group__is_active=True
    ).select_related('group').first()

    room_group_data = None
    if room_membership:
        room_group_data = build_group_context(room_membership.group, target_user, today, selected_year, selected_month)

    # Trip Sharing group (uses target_user so viewers see owner's trip)
    trip_membership = SharingGroupMembership.objects.filter(
        user=target_user,
        group__group_type='trip',
        group__is_active=True
    ).select_related('group').first()

    trip_group_data = None
    if trip_membership:
        trip_group_data = build_group_context(trip_membership.group, target_user, today, selected_year, selected_month)

    context = {
        'profile': target_profile,
        'viewer_profile': user_profile if is_viewer else None,
        'current_tracker': 'sharing',
        'active_mode': active_mode,
        'active_toggle': active_mode,
        'room_group': room_group_data,
        'trip_group': trip_group_data,
        'has_room_group': bool(room_group_data),
        'has_trip_group': bool(trip_group_data),
        'today': today,
        'selected_month': selected_month,
        'selected_year': selected_year,
        'month_name': month_name,
        'months_list': months_list,
        'years_list': years_list,
        'is_viewer': is_viewer,
    }
    return render(request, 'expenses/room_tracker.html', context)


@login_required
def settle_shared_scenario_view(request, group_id):
    """
    Settles (clears) or reopens an entire subgroup scenario (e.g. ABC, AB, AC, BC).
    All expenses matching this group and participant set are marked is_settled=True.
    """
    if hasattr(request.user, 'profile') and request.user.profile.is_viewer:
        messages.error(request, "Viewers have read-only access and cannot settle expenses.")
        return redirect('room_tracker')

    if request.method != 'POST':
        return redirect('room_tracker')

    group = get_object_or_404(SharingGroup, id=group_id)
    if not group.memberships.filter(user=request.user).exists():
        messages.error(request, "Permission denied.")
        return redirect('room_tracker')

    scenario_code = request.POST.get('scenario_code', '').strip()
    participant_ids_raw = request.POST.get('participant_ids', '[]')
    action = request.POST.get('action', 'settle').strip().lower()

    try:
        participant_ids = [int(x) for x in json.loads(participant_ids_raw)]
    except Exception:
        participant_ids = []

    matching_expenses = []
    for exp in group.expenses.prefetch_related('split_members').all():
        splits = sorted([u.id for u in exp.split_members.all()])
        if splits == sorted(participant_ids):
            matching_expenses.append(exp)

    if action == 'unsettle':
        for exp in matching_expenses:
            exp.is_settled = False
            exp.settled_at = None
            exp.settled_by = None
            exp.save()
        messages.success(request, f"✓ Subgroup scenario {scenario_code} has been reopened. Balances are active.")
    else:
        now = timezone.now()
        for exp in matching_expenses:
            exp.is_settled = True
            exp.settled_at = now
            exp.settled_by = request.user
            exp.save()
        messages.success(request, f"✓ Subgroup scenario {scenario_code} successfully marked as settled and cleared!")

    mode = group.group_type
    month = request.POST.get('month', '')
    year = request.POST.get('year', '')
    redirect_url = f"/room-tracker/?mode={mode}"
    if month:
        redirect_url += f"&month={month}"
    if year:
        redirect_url += f"&year={year}"

    actor_name = _actor_display_name(request.user)
    if action == 'unsettle':
        _notify_group_members(
            group,
            request.user,
            'reopened',
            f"{actor_name} reopened subgroup {scenario_code} in {group.name}",
            f"{redirect_url}&open_breakdown={request.user.id}",
        )
    else:
        _notify_group_members(
            group,
            request.user,
            'settled',
            f"{actor_name} settled subgroup {scenario_code} in {group.name}",
            f"{redirect_url}&open_breakdown={request.user.id}",
        )

    return redirect(redirect_url)


@login_required
def create_sharing_group_view(request):
    """
    Creates a new SharingGroup (Room or Trip) with configured member count & generated passkey.
    """
    if hasattr(request.user, 'profile') and request.user.profile.is_viewer:
        messages.error(request, "Viewers cannot create sharing groups.")
        return redirect('room_tracker')

    if request.method == 'POST':
        group_type = request.POST.get('group_type', 'room').strip().lower()
        if group_type not in ['room', 'trip']:
            group_type = 'room'

        existing = SharingGroupMembership.objects.filter(
            user=request.user,
            group__group_type=group_type,
            group__is_active=True
        ).first()

        if existing:
            messages.info(request, f"You are already in an active {group_type.capitalize()} Sharing group ({existing.group.passkey}).")
            return redirect(f"/room-tracker/?mode={group_type}")

        raw_members = request.POST.get('total_members', '2')
        try:
            total_members = max(2, min(50, int(raw_members)))
        except (ValueError, TypeError):
            total_members = 2

        prefix = 'ROOM' if group_type == 'room' else 'TRIP'
        default_name = 'Room Sharing' if group_type == 'room' else 'Trip Sharing'
        name = request.POST.get('name', default_name).strip() or default_name

        passkey = generate_sharing_passkey(prefix=prefix)

        group = SharingGroup.objects.create(
            group_type=group_type,
            name=name,
            passkey=passkey,
            total_members=total_members,
            creator=request.user,
            is_active=True
        )

        SharingGroupMembership.objects.create(
            group=group,
            user=request.user,
            role='creator'
        )

        messages.success(request, f"🎉 {default_name} created successfully! Passkey: {passkey}")
        return redirect(f"/room-tracker/?mode={group_type}")

    return redirect('room_tracker')


@login_required
def join_sharing_group_view(request):
    """
    Allows a user to join an existing Room or Trip group with a Passkey.
    """
    if hasattr(request.user, 'profile') and request.user.profile.is_viewer:
        messages.error(request, "Viewers cannot join sharing groups.")
        return redirect('room_tracker')

    if request.method == 'POST':
        raw_passkey = request.POST.get('passkey', '').strip().upper()
        group_type_hint = request.POST.get('group_type', 'room').strip().lower()

        if not raw_passkey:
            messages.error(request, "Please enter a valid Passkey to join.")
            return redirect(f"/room-tracker/?mode={group_type_hint}")

        group = SharingGroup.objects.filter(passkey__iexact=raw_passkey, is_active=True).first()

        if not group:
            messages.error(request, f"No active sharing group found with Passkey '{raw_passkey}'. Please verify the code.")
            return redirect(f"/room-tracker/?mode={group_type_hint}")

        # Check if already a member
        if SharingGroupMembership.objects.filter(group=group, user=request.user).exists():
            messages.info(request, f"You are already a member of {group.name} ({group.passkey}).")
            return redirect(f"/room-tracker/?mode={group.group_type}")

        # Check if group is full
        if group.is_full:
            messages.error(request, f"This group has reached its maximum limit ({group.total_members} members).")
            return redirect(f"/room-tracker/?mode={group.group_type}")

        # Check if user already in another active group of the same type
        existing_other = SharingGroupMembership.objects.filter(
            user=request.user,
            group__group_type=group.group_type,
            group__is_active=True
        ).first()

        if existing_other:
            messages.error(
                request,
                f"You already belong to another {group.get_group_type_display()} group ({existing_other.group.passkey}). Leave that group first before joining a new one."
            )
            return redirect(f"/room-tracker/?mode={group.group_type}")

        # Add user as member
        SharingGroupMembership.objects.create(
            group=group,
            user=request.user,
            role='member'
        )

        actor_name = _actor_display_name(request.user)
        _notify_group_members(
            group,
            request.user,
            'joined',
            f"{actor_name} joined {group.name}",
            f"/room-tracker/?mode={group.group_type}",
        )

        messages.success(request, f"🎉 You have joined {group.name}! Passkey: {group.passkey}")
        return redirect(f"/room-tracker/?mode={group.group_type}")

    return redirect('room_tracker')

    return redirect('room_tracker')


@login_required
def leave_sharing_group_view(request, group_id):
    """
    Allows a member to leave or creator to dissolve a sharing group.
    """
    if hasattr(request.user, 'profile') and request.user.profile.is_viewer:
        messages.error(request, "Viewers cannot leave or dissolve sharing groups.")
        return redirect('room_tracker')

    membership = get_object_or_404(SharingGroupMembership, group_id=group_id, user=request.user)
    group = membership.group
    group_type = group.group_type

    if request.method == 'POST':
        if group.creator == request.user:
            group.is_active = False
            group.save()
            messages.success(request, f"Dissolved {group.name} ({group.passkey}).")
        else:
            membership.delete()
            messages.success(request, f"You have left {group.name} ({group.passkey}).")

    return redirect(f"/room-tracker/?toggle={group_type}")


@login_required
def add_shared_expense_view(request):
    """
    Handles adding a new shared expense in a SharingGroup (Room or Trip).
    Accessible to all members of the group.
    Supports selecting who paid and which members share the bill.
    """
    if hasattr(request.user, 'profile') and request.user.profile.is_viewer:
        messages.error(request, "Viewers have read-only access and cannot add shared bills.")
        return redirect('room_tracker')

    if request.method == 'POST':
        group_id = request.POST.get('group_id')
        group = get_object_or_404(SharingGroup, id=group_id, is_active=True)

        # Verify user is a member of this group
        if not SharingGroupMembership.objects.filter(group=group, user=request.user).exists():
            messages.error(request, "You are not a member of this group.")
            return redirect('room_tracker')

        date_str = request.POST.get('date', '').strip()
        description = request.POST.get('description', '').strip()
        category = request.POST.get('category', '').strip() or 'Food & Dining'
        raw_amount = request.POST.get('amount', '').strip()
        paid_by_id = request.POST.get('paid_by', '').strip()
        split_member_ids = request.POST.getlist('split_members')

        try:
            amount = Decimal(raw_amount)
            if amount <= Decimal('0.00'):
                raise ValueError()
        except (ValueError, TypeError, InvalidOperation):
            messages.error(request, "Please enter a valid positive bill amount.")
            return redirect(f"/room-tracker/?mode={group.group_type}")

        if not description:
            messages.error(request, "Please enter a bill purpose / description.")
            return redirect(f"/room-tracker/?mode={group.group_type}")

        try:
            exp_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else datetime.date.today()
        except ValueError:
            exp_date = datetime.date.today()

        # Resolve payer
        paid_by_user = request.user
        if paid_by_id:
            candidate = User.objects.filter(id=paid_by_id).first()
            if candidate and SharingGroupMembership.objects.filter(group=group, user=candidate).exists():
                paid_by_user = candidate

        # Resolve split members
        group_members = [m.user for m in group.memberships.all()]
        if split_member_ids:
            selected_users = [u for u in group_members if str(u.id) in split_member_ids]
            if not selected_users:
                selected_users = group_members
        else:
            selected_users = group_members

        # Optional future months split
        is_split = request.POST.get('is_split') == 'true'
        try:
            split_months = max(1, min(24, int(request.POST.get('split_months', '1')))) if is_split else 1
        except (ValueError, TypeError):
            split_months = 1

        payer_name = paid_by_user.profile.display_name if hasattr(paid_by_user, 'profile') else paid_by_user.username
        split_count = len(selected_users)

        if is_split and split_months > 1:
            installments = _build_monthly_installments(exp_date, amount, split_months)
            created_rows = []
            for t_date, m_amt, suffix in installments:
                exp_row = SharedExpense.objects.create(
                    group=group,
                    paid_by=paid_by_user,
                    date=t_date,
                    description=f"{description}{suffix}",
                    category=category,
                    amount=m_amt,
                    created_by=request.user,
                )
                exp_row.split_members.set(selected_users)
                created_rows.append(exp_row)

            first_str = installments[0][0].strftime('%b %Y')
            last_str = installments[-1][0].strftime('%b %Y')
            actor_name = _actor_display_name(request.user)
            first_id = created_rows[0].id
            _notify_group_members(
                group,
                request.user,
                'added',
                f"{actor_name} added '{description}' (₹{amount:,.2f} across {split_months} mos) in {group.name}",
                f"/room-tracker/?mode={group.group_type}&month={exp_date.month}&year={exp_date.year}#{group.group_type}-exp-{first_id}",
            )
            messages.success(
                request,
                f"🎉 Added bill '₹{amount} - {description}' split across {split_months} future months ({first_str} to {last_str}) among {split_count} members!"
            )
            return redirect(f"/room-tracker/?mode={group.group_type}&month={exp_date.month}&year={exp_date.year}")

        # Standard single SharedExpense
        expense = SharedExpense.objects.create(
            group=group,
            paid_by=paid_by_user,
            date=exp_date,
            description=description,
            category=category,
            amount=amount,
            created_by=request.user,
        )
        expense.split_members.set(selected_users)

        actor_name = _actor_display_name(request.user)
        _notify_group_members(
            group,
            request.user,
            'added',
            f"{actor_name} added '{description}' (₹{amount:,.2f}) in {group.name}",
            f"/room-tracker/?mode={group.group_type}&month={exp_date.month}&year={exp_date.year}#{group.group_type}-exp-{expense.id}",
        )

        per_head = (amount / Decimal(split_count)).quantize(Decimal('0.01'))
        messages.success(
            request,
            f"🎉 Added bill '₹{amount} - {description}' paid by {payer_name} (Split between {split_count} members: ₹{per_head} each)!"
        )
        return redirect(f"/room-tracker/?mode={group.group_type}&month={exp_date.month}&year={exp_date.year}")

    return redirect('room_tracker')


@login_required
def edit_shared_expense_view(request, expense_id):
    """
    Handles editing an existing shared expense in a SharingGroup (Room or Trip).
    Permitted ONLY to the user who entered the bill (created_by) or paid for it (paid_by).
    """
    if hasattr(request.user, 'profile') and request.user.profile.is_viewer:
        messages.error(request, "Viewers have read-only access and cannot edit bills.")
        return redirect('room_tracker')

    expense = get_object_or_404(SharedExpense, id=expense_id)
    group = expense.group

    # Verify user entered the bill or paid for it
    if expense.created_by != request.user and expense.paid_by != request.user:
        messages.error(request, "Permission denied: Only the person who entered or paid this bill can edit it.")
        return redirect(f"/room-tracker/?mode={group.group_type}")

    if request.method == 'POST':
        date_str = request.POST.get('date', '').strip()
        description = request.POST.get('description', '').strip()
        category = request.POST.get('category', '').strip() or expense.category
        raw_amount = request.POST.get('amount', '').strip()
        paid_by_id = request.POST.get('paid_by', '').strip()
        split_member_ids = request.POST.getlist('split_members')

        try:
            amount = Decimal(raw_amount)
            if amount <= Decimal('0.00'):
                raise ValueError()
        except (ValueError, TypeError, InvalidOperation):
            messages.error(request, "Please enter a valid positive bill amount.")
            return redirect(f"/room-tracker/?mode={group.group_type}")

        if not description:
            messages.error(request, "Please enter a bill purpose / description.")
            return redirect(f"/room-tracker/?mode={group.group_type}")

        try:
            exp_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else expense.date
        except ValueError:
            exp_date = expense.date

        # Resolve payer
        if paid_by_id:
            candidate = User.objects.filter(id=paid_by_id).first()
            if candidate and SharingGroupMembership.objects.filter(group=group, user=candidate).exists():
                expense.paid_by = candidate

        expense.date = exp_date
        expense.description = description
        expense.category = category
        expense.amount = amount
        expense.save()

        # Update split members
        group_members = [m.user for m in group.memberships.all()]
        if split_member_ids:
            selected_users = [u for u in group_members if str(u.id) in split_member_ids]
            if not selected_users:
                selected_users = group_members
        else:
            selected_users = group_members

        expense.split_members.set(selected_users)

        actor_name = _actor_display_name(request.user)
        _notify_group_members(
            group,
            request.user,
            'edited',
            f"{actor_name} updated '{expense.description}' (₹{expense.amount:,.2f}) in {group.name}",
            f"/room-tracker/?mode={group.group_type}&month={expense.date.month}&year={expense.date.year}#{group.group_type}-exp-{expense.id}",
        )

        messages.success(request, f"Updated bill '₹{expense.amount} - {expense.description}' successfully!")
        return redirect(f"/room-tracker/?mode={group.group_type}&month={expense.date.month}&year={expense.date.year}")

    return redirect(f"/room-tracker/?mode={group.group_type}")


@login_required
def delete_shared_expense_view(request, expense_id):
    """
    Deletes a shared expense. Permitted ONLY for the payer or the person who entered the bill.
    """
    if hasattr(request.user, 'profile') and request.user.profile.is_viewer:
        messages.error(request, "Viewers have read-only access and cannot delete bills.")
        return redirect('room_tracker')

    expense = get_object_or_404(SharedExpense, id=expense_id)
    group = expense.group

    # Verify user is the one who entered or paid for the bill
    if expense.created_by != request.user and expense.paid_by != request.user:
        messages.error(request, "Permission denied: Only the person who entered or paid this bill can delete it.")
        return redirect(f"/room-tracker/?mode={group.group_type}")

    if request.method == 'POST':
        amt = expense.amount
        desc = expense.description
        exp_date = expense.date
        expense.delete()

        actor_name = _actor_display_name(request.user)
        history_sec = "tripHistorySection" if group.group_type == 'trip' else "roomHistorySection"
        _notify_group_members(
            group,
            request.user,
            'deleted',
            f"{actor_name} deleted bill '{desc}' (₹{amt:,.2f}) in {group.name}",
            f"/room-tracker/?mode={group.group_type}&month={exp_date.month}&year={exp_date.year}#{history_sec}",
        )
        messages.success(request, f"Deleted bill '₹{amt} - {desc}'.")

    return redirect(f"/room-tracker/?mode={group.group_type}")


@login_required
def update_profile_view(request):
    """
    Allows the user to view and update their profile details (Full name, Age, Avatar).
    """
    if hasattr(request.user, 'profile') and request.user.profile.is_viewer:
        messages.error(request, "Viewers cannot update owner profile.")
        return redirect('home')

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        if request.POST.get('remove_avatar') == '1':
            if profile.avatar:
                profile.avatar.delete(save=False)
                profile.avatar = None
                profile.save()
                messages.success(request, "Profile picture removed.")
            return redirect('update_profile')

        form = ProfileSetupForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            p = form.save(commit=False)
            p.is_profile_setup = True
            p.save()
            messages.success(request, "Profile updated successfully!")
            return redirect('home')
    else:
        form = ProfileSetupForm(instance=profile)

    return render(request, 'expenses/profile_update.html', {
        'form': form,
        'profile': profile,
        'current_tracker': 'personal',
    })


@login_required
def create_viewer_view(request):
    """
    Allows the super admin / owner to create read-only viewer accounts for family/friends.
    """
    if request.user.profile.is_viewer:
        messages.error(request, "Viewers cannot create other viewers.")
        return redirect('home')

    if request.method == 'POST':
        form = CreateViewerForm(request.POST)
        if form.is_valid():
            full_name = form.cleaned_data['full_name'].strip()
            username = form.cleaned_data['username'].strip()
            password = form.cleaned_data['password']

            email = username if '@' in username else ''
            viewer_user = User.objects.create_user(
                username=username,
                email=email,
                password=password
            )
            UserProfile.objects.create(
                user=viewer_user,
                full_name=full_name or username,
                is_profile_setup=True,
                is_viewer=True,
                viewer_of=request.user
            )
            messages.success(request, f"Viewer profile '{username}' created successfully! They can log in to view your tracker.")
            return redirect('create_viewer')
    else:
        form = CreateViewerForm()

    existing_viewers = User.objects.filter(profile__viewer_of=request.user, profile__is_viewer=True).select_related('profile').order_by('-date_joined')

    return render(request, 'expenses/create_viewer.html', {
        'form': form,
        'viewers': existing_viewers,
        'current_tracker': 'viewer',
        'profile': request.user.profile,
    })


@login_required
def delete_viewer_view(request, viewer_id):
    """
    Revoke and delete a viewer profile created by this admin.
    """
    if request.user.profile.is_viewer:
        messages.error(request, "Permission denied.")
        return redirect('home')

    viewer_user = get_object_or_404(User, id=viewer_id, profile__viewer_of=request.user)
    if request.method == 'POST':
        uname = viewer_user.username
        viewer_user.delete()
        messages.success(request, f"Viewer account '{uname}' has been revoked.")

    return redirect('create_viewer')


# =============================================================================
# LEND & BORROW TRACKER (Money Given / Money Taken with Optional Interest)
# =============================================================================
@login_required
def lend_borrow_view(request):
    """
    Lend & Borrow Tracker:
    - Tab 1: Given to Others (Money Lent / I Gave)
    - Tab 2: Taken from Others (Money Borrowed / I Took)
    - Supports simple interest calculation, repayment dates, and settlement status.
    - Viewers have read-only view of admin/owner's loan records.
    """
    user_profile, _ = UserProfile.objects.get_or_create(user=request.user)
    is_viewer = hasattr(request.user, 'profile') and request.user.profile.is_viewer
    if is_viewer and request.user.profile.viewer_of:
        target_user = request.user.profile.viewer_of
        target_profile = getattr(target_user, 'profile', user_profile)
    else:
        target_user = request.user
        target_profile = user_profile

    active_tab = request.GET.get('tab', 'given').strip().lower()
    if active_tab not in ['given', 'taken']:
        active_tab = 'given'

    today = datetime.date.today()

    # Query all records
    given_records = list(LoanRecord.objects.filter(user=target_user, transaction_type='given'))
    taken_records = list(LoanRecord.objects.filter(user=target_user, transaction_type='taken'))

    # Calculate KPIs for Given (Lent)
    given_pending = [r for r in given_records if r.status == 'pending']
    given_settled = [r for r in given_records if r.status == 'settled']
    given_principal_pending = sum((r.amount for r in given_pending), Decimal('0.00'))
    given_interest_pending = sum((r.calculated_interest for r in given_pending), Decimal('0.00'))
    given_total_pending = sum((r.total_expected_amount for r in given_pending), Decimal('0.00'))
    given_lifetime_principal = sum((r.amount for r in given_records), Decimal('0.00'))

    # Calculate KPIs for Taken (Borrowed)
    taken_pending = [r for r in taken_records if r.status == 'pending']
    taken_settled = [r for r in taken_records if r.status == 'settled']
    taken_principal_pending = sum((r.amount for r in taken_pending), Decimal('0.00'))
    taken_interest_pending = sum((r.calculated_interest for r in taken_pending), Decimal('0.00'))
    taken_total_pending = sum((r.total_expected_amount for r in taken_pending), Decimal('0.00'))
    taken_lifetime_principal = sum((r.amount for r in taken_records), Decimal('0.00'))

    context = {
        'profile': target_profile,
        'current_tracker': 'lend_borrow',
        'active_tab': active_tab,
        'today': today,
        'is_viewer': is_viewer,
        'given_records': given_records,
        'taken_records': taken_records,
        'given_stats': {
            'pending_count': len(given_pending),
            'settled_count': len(given_settled),
            'total_records': len(given_records),
            'principal_pending': given_principal_pending,
            'interest_pending': given_interest_pending,
            'total_pending': given_total_pending,
            'lifetime_principal': given_lifetime_principal,
        },
        'taken_stats': {
            'pending_count': len(taken_pending),
            'settled_count': len(taken_settled),
            'total_records': len(taken_records),
            'principal_pending': taken_principal_pending,
            'interest_pending': taken_interest_pending,
            'total_pending': taken_total_pending,
            'lifetime_principal': taken_lifetime_principal,
        },
    }
    return render(request, 'expenses/lend_borrow.html', context)


@login_required
def add_loan_record_view(request):
    """
    Adds a new loan record (Given to others or Taken from others).
    """
    if hasattr(request.user, 'profile') and request.user.profile.is_viewer:
        messages.error(request, "Viewers have read-only access.")
        return redirect('lend_borrow')

    if request.method == 'POST':
        ttype = request.POST.get('transaction_type', 'given').strip().lower()
        if ttype not in ['given', 'taken']:
            ttype = 'given'

        person_name = request.POST.get('person_name', '').strip()
        phone = request.POST.get('phone', '').strip()
        amount_raw = request.POST.get('amount', '').strip()
        given_date_raw = request.POST.get('given_date', '').strip()
        expected_date_raw = request.POST.get('expected_return_date', '').strip()
        has_interest = request.POST.get('has_interest') in ['true', 'on', '1']
        interest_rate_raw = request.POST.get('interest_rate', '0').strip()
        interest_period = request.POST.get('interest_period', 'month').strip().lower()
        duration_val_raw = request.POST.get('duration_value', '1').strip()
        duration_unit = request.POST.get('duration_unit', 'months').strip().lower()
        notes = request.POST.get('notes', '').strip()

        if not person_name:
            messages.error(request, "Person name is required.")
            return redirect(f"/lend-borrow/?tab={ttype}")

        try:
            amount = Decimal(amount_raw)
            if amount <= Decimal('0.00'):
                raise ValueError()
        except Exception:
            messages.error(request, "Please enter a valid amount greater than ₹0.")
            return redirect(f"/lend-borrow/?tab={ttype}")

        try:
            given_date = datetime.date.fromisoformat(given_date_raw) if given_date_raw else datetime.date.today()
        except Exception:
            given_date = datetime.date.today()

        expected_return_date = None
        if expected_date_raw:
            try:
                expected_return_date = datetime.date.fromisoformat(expected_date_raw)
            except Exception:
                expected_return_date = None

        if has_interest:
            try:
                interest_rate = Decimal(interest_rate_raw)
                if interest_rate < Decimal('0.00'):
                    interest_rate = Decimal('0.00')
            except Exception:
                interest_rate = Decimal('0.00')

            try:
                duration_val = int(duration_val_raw)
                if duration_val < 1:
                    duration_val = 1
            except Exception:
                duration_val = 1
        else:
            interest_rate = Decimal('0.00')
            duration_val = 1

        record = LoanRecord.objects.create(
            user=request.user,
            transaction_type=ttype,
            person_name=person_name,
            phone=phone or None,
            amount=amount,
            given_date=given_date,
            expected_return_date=expected_return_date,
            has_interest=has_interest,
            interest_rate=interest_rate,
            interest_period=interest_period if interest_period in ['month', 'year'] else 'month',
            duration_value=duration_val,
            duration_unit=duration_unit if duration_unit in ['months', 'years'] else 'months',
            notes=notes,
            status='pending',
        )

        type_label = "Given (Lent)" if ttype == 'given' else "Taken (Borrowed)"
        messages.success(request, f"✓ Successfully added ₹{amount:,.2f} {type_label} for {person_name}!")
        return redirect(f"/lend-borrow/?tab={ttype}")

    return redirect('lend_borrow')


@login_required
def edit_loan_record_view(request, record_id):
    """
    Edits an existing loan record.
    """
    if hasattr(request.user, 'profile') and request.user.profile.is_viewer:
        messages.error(request, "Viewers have read-only access.")
        return redirect('lend_borrow')

    record = get_object_or_404(LoanRecord, id=record_id, user=request.user)

    if request.method == 'POST':
        person_name = request.POST.get('person_name', '').strip()
        phone = request.POST.get('phone', '').strip()
        amount_raw = request.POST.get('amount', '').strip()
        given_date_raw = request.POST.get('given_date', '').strip()
        expected_date_raw = request.POST.get('expected_return_date', '').strip()
        has_interest = request.POST.get('has_interest') in ['true', 'on', '1']
        interest_rate_raw = request.POST.get('interest_rate', '0').strip()
        interest_period = request.POST.get('interest_period', 'month').strip().lower()
        duration_val_raw = request.POST.get('duration_value', '1').strip()
        duration_unit = request.POST.get('duration_unit', 'months').strip().lower()
        notes = request.POST.get('notes', '').strip()

        if person_name:
            record.person_name = person_name
        record.phone = phone or None

        try:
            amount = Decimal(amount_raw)
            if amount > Decimal('0.00'):
                record.amount = amount
        except Exception:
            pass

        try:
            if given_date_raw:
                record.given_date = datetime.date.fromisoformat(given_date_raw)
        except Exception:
            pass

        try:
            if expected_date_raw:
                record.expected_return_date = datetime.date.fromisoformat(expected_date_raw)
            else:
                record.expected_return_date = None
        except Exception:
            record.expected_return_date = None

        record.has_interest = has_interest
        if has_interest:
            try:
                record.interest_rate = Decimal(interest_rate_raw)
            except Exception:
                record.interest_rate = Decimal('0.00')

            try:
                record.duration_value = max(1, int(duration_val_raw))
            except Exception:
                record.duration_value = 1

            record.interest_period = interest_period if interest_period in ['month', 'year'] else 'month'
            record.duration_unit = duration_unit if duration_unit in ['months', 'years'] else 'months'
        else:
            record.interest_rate = Decimal('0.00')

        record.notes = notes
        record.save()

        messages.success(request, f"✓ Updated record for {record.person_name} successfully!")
        return redirect(f"/lend-borrow/?tab={record.transaction_type}")

    return redirect(f"/lend-borrow/?tab={record.transaction_type}")


@login_required
def delete_loan_record_view(request, record_id):
    """
    Deletes an existing loan record.
    """
    if hasattr(request.user, 'profile') and request.user.profile.is_viewer:
        messages.error(request, "Viewers have read-only access.")
        return redirect('lend_borrow')

    record = get_object_or_404(LoanRecord, id=record_id, user=request.user)
    ttype = record.transaction_type
    pname = record.person_name
    record.delete()
    messages.success(request, f"🗑️ Deleted entry for {pname}.")
    return redirect(f"/lend-borrow/?tab={ttype}")


@login_required
def toggle_loan_settled_view(request, record_id):
    """
    Toggles the settlement status of a loan record (Pending <-> Settled).
    """
    if hasattr(request.user, 'profile') and request.user.profile.is_viewer:
        messages.error(request, "Viewers have read-only access.")
        return redirect('lend_borrow')

    record = get_object_or_404(LoanRecord, id=record_id, user=request.user)
    if record.status == 'pending':
        record.status = 'settled'
        record.settled_at = timezone.now()
        action_msg = "marked as settled/returned" if record.transaction_type == 'given' else "marked as settled/repaid"
        messages.success(request, f"✓ Record for {record.person_name} has been {action_msg}!")
    else:
        record.status = 'pending'
        record.settled_at = None
        messages.info(request, f"↺ Record for {record.person_name} reopened as pending.")

    record.save()
    return redirect(f"/lend-borrow/?tab={record.transaction_type}")


# =============================================================================
# ANALYTICS DASHBOARD (All-in-One Pie Charts Landing Page)
# =============================================================================
@login_required
def analytics_view(request):
    """
    Landing dashboard after login. Displays interactive SVG Pie Charts for:
    - Personal Tracking (by Category)
    - Room Tracking (by Category)
    - Trip Sharing (by Category)
    - Money Borrow & Lend (Overview, Given by Person, Borrowed by Person)
    Hovering a slice displays exact amount; resting state shows category + %.
    Totals are prominently shown below each pie chart.
    """
    is_viewer, target_user, target_profile, user_profile = _resolve_target_user(request)

    if not is_viewer and not target_profile.is_profile_setup:
        return redirect('home')

    today = datetime.date.today()
    period = _parse_month_year_params(request, today)
    selected_year = period['selected_year']
    selected_month = period['selected_month']
    is_full_year = period['is_full_year']
    month_name = period['month_name']
    period_label = f"Full Year {selected_year}" if is_full_year else f"{month_name} {selected_year}"

    # 1. Personal Tracking Pie Data (matches Personal Tracker unified expenses)
    personal_year = _get_personal_unified_expenses(target_user, selected_year)
    personal_period = personal_year if is_full_year else [e for e in personal_year if e.date.month == selected_month]
    personal_cat_totals = defaultdict(Decimal)
    for exp in personal_period:
        cat_name = exp.category.strip() if exp.category else 'Other'
        personal_cat_totals[cat_name] += exp.amount
    personal_total, personal_slices = _build_pie_slices(personal_cat_totals)

    # 2. Room Tracking Pie Data
    room_membership = SharingGroupMembership.objects.filter(
        user=target_user,
        group__group_type='room',
        group__is_active=True
    ).select_related('group').first()

    room_group_name = ''
    room_cat_totals = defaultdict(Decimal)
    if room_membership:
        room_group_name = room_membership.group.name
        room_qs = SharedExpense.objects.filter(
            group=room_membership.group,
            date__year=selected_year
        )
        if not is_full_year:
            room_qs = room_qs.filter(date__month=selected_month)
        for exp in room_qs:
            cat_name = exp.category.strip() if exp.category else 'Other'
            room_cat_totals[cat_name] += exp.amount
    room_total, room_slices = _build_pie_slices(room_cat_totals)

    # 3. Trip Sharing Pie Data
    trip_membership = SharingGroupMembership.objects.filter(
        user=target_user,
        group__group_type='trip',
        group__is_active=True
    ).select_related('group').first()

    trip_group_name = ''
    trip_cat_totals = defaultdict(Decimal)
    if trip_membership:
        trip_group_name = trip_membership.group.name
        trip_qs = SharedExpense.objects.filter(
            group=trip_membership.group,
            date__year=selected_year
        )
        if not is_full_year:
            trip_qs = trip_qs.filter(date__month=selected_month)
        for exp in trip_qs:
            cat_name = exp.category.strip() if exp.category else 'Other'
            trip_cat_totals[cat_name] += exp.amount
    trip_total, trip_slices = _build_pie_slices(trip_cat_totals, palette=[
        '#0f766e', '#0ea5e9', '#14b8a6', '#f59e0b', '#6366f1', '#ec4899', '#8b5cf6', '#f97316'
    ])

    # 4. Money Borrow & Lend Pie Data (All active & settled ledger records)
    all_loans = list(LoanRecord.objects.filter(user=target_user))
    loan_overview_totals = defaultdict(Decimal)
    loan_given_person_totals = defaultdict(Decimal)
    loan_taken_person_totals = defaultdict(Decimal)
    total_given_expected = Decimal('0.00')
    total_taken_expected = Decimal('0.00')

    for loan in all_loans:
        amt = loan.total_expected_amount
        if loan.transaction_type == 'given':
            total_given_expected += amt
            label = "Money Given (Settled)" if loan.status == 'settled' else "Money Given (Pending)"
            loan_overview_totals[label] += amt
            loan_given_person_totals[loan.person_name] += amt
        else:
            total_taken_expected += amt
            label = "Money Borrowed (Settled)" if loan.status == 'settled' else "Money Borrowed (Pending)"
            loan_overview_totals[label] += amt
            loan_taken_person_totals[loan.person_name] += amt

    loan_overview_total, loan_overview_slices = _build_pie_slices(loan_overview_totals, palette=[
        '#10b981', '#0f766e', '#ef4444', '#f97316'
    ])
    loan_given_total, loan_given_slices = _build_pie_slices(loan_given_person_totals, palette=[
        '#10b981', '#0f766e', '#06b6d4', '#3b82f6', '#8b5cf6'
    ])
    loan_taken_total, loan_taken_slices = _build_pie_slices(loan_taken_person_totals, palette=[
        '#ef4444', '#f97316', '#ec4899', '#f59e0b', '#6366f1'
    ])

    analytics_payload = {
        'personal': {
            'total': float(personal_total),
            'total_formatted': f"₹{personal_total:,.2f}",
            'slices': personal_slices,
        },
        'room': {
            'total': float(room_total),
            'total_formatted': f"₹{room_total:,.2f}",
            'slices': room_slices,
        },
        'trip': {
            'total': float(trip_total),
            'total_formatted': f"₹{trip_total:,.2f}",
            'slices': trip_slices,
        },
        'loan_overview': {
            'total': float(loan_overview_total),
            'total_formatted': f"₹{loan_overview_total:,.2f}",
            'slices': loan_overview_slices,
        },
        'loan_given': {
            'total': float(loan_given_total),
            'total_formatted': f"₹{loan_given_total:,.2f}",
            'slices': loan_given_slices,
        },
        'loan_taken': {
            'total': float(loan_taken_total),
            'total_formatted': f"₹{loan_taken_total:,.2f}",
            'slices': loan_taken_slices,
        },
    }

    context = {
        'profile': target_profile,
        'is_viewer': is_viewer,
        'current_tracker': 'analytics',
        'selected_year': selected_year,
        'selected_month': selected_month,
        'is_full_year': is_full_year,
        'month_name': month_name,
        'period_label': period_label,
        'months_list': period['months_list'],
        'years_list': period['years_list'],
        'personal_total': personal_total,
        'personal_count': len(personal_period),
        'has_room_group': bool(room_membership),
        'room_group_name': room_group_name,
        'room_total': room_total,
        'has_trip_group': bool(trip_membership),
        'trip_group_name': trip_group_name,
        'trip_total': trip_total,
        'total_given_expected': total_given_expected,
        'total_taken_expected': total_taken_expected,
        'loan_overview_total': loan_overview_total,
        'analytics_payload_json': json.dumps(analytics_payload, cls=DjangoJSONEncoder),
    }
    return render(request, 'expenses/analytics.html', context)


# =============================================================================
# PDF EXPORT ENDPOINTS (Personal, Room/Trip Sharing & Category Popups, Lend/Borrow)
# =============================================================================
@login_required
def export_personal_pdf_view(request):
    """Exports Personal Tracker history (including optional active filters or popup category) to PDF."""
    is_viewer, target_user, target_profile, _ = _resolve_target_user(request)
    today = datetime.date.today()
    period = _parse_month_year_params(request, today)
    selected_year = period['selected_year']
    selected_month = period['selected_month']
    is_full_year = period['is_full_year']
    period_label = f"Full Year {selected_year}" if is_full_year else f"{period['month_name']} {selected_year}"

    year_expenses = _get_personal_unified_expenses(target_user, selected_year)
    expenses = year_expenses if is_full_year else [e for e in year_expenses if e.date.month == selected_month]

    selected_category = request.GET.get('category', '').strip()
    filter_date = request.GET.get('date', '').strip()
    min_amount_param = request.GET.get('min_amount', '').strip()
    max_amount_param = request.GET.get('max_amount', '').strip()

    filter_parts = [f"Account: {target_profile.display_name}", f"Period: {period_label}"]

    if selected_category and selected_category.lower() != 'all':
        expenses = [e for e in expenses if (e.category or '').strip().lower() == selected_category.lower()]
        filter_parts.append(f"Category: {selected_category}")
    if filter_date:
        try:
            parsed_d = datetime.date.fromisoformat(filter_date)
            expenses = [e for e in expenses if e.date == parsed_d]
            filter_parts.append(f"Date: {parsed_d.strftime('%d/%m/%Y')}")
        except ValueError:
            pass
    if min_amount_param:
        try:
            min_val = Decimal(min_amount_param)
            expenses = [e for e in expenses if e.amount >= min_val]
            filter_parts.append(f"Min: {format_inr(min_val)}")
        except Exception:
            pass
    if max_amount_param:
        try:
            max_val = Decimal(max_amount_param)
            expenses = [e for e in expenses if e.amount <= max_val]
            filter_parts.append(f"Max: {format_inr(max_val)}")
        except Exception:
            pass

    rows = []
    total_amt = Decimal('0.00')
    for exp in expenses:
        is_shared = getattr(exp, 'is_shared', False)
        source_text = f"{exp.group_name} Share (of {format_inr(exp.shared_total_bill)})" if is_shared else "Personal Entry"
        total_amt += exp.amount
        rows.append([
            exp.date.strftime('%d/%m/%Y'),
            exp.description,
            exp.category or 'Other',
            source_text,
            format_inr(exp.amount),
        ])

    title = f"Personal Expenses - {selected_category}" if (selected_category and selected_category.lower() != 'all') else "Personal Tracker Expense History"
    safe_cat = "".join(ch if ch.isalnum() else "_" for ch in selected_category) if selected_category else "all"
    filename = f"RupeeRoute_Personal_{safe_cat}_{selected_year}_{selected_month}.pdf"

    return build_pdf_response(
        filename=filename,
        title=title,
        subtitle=" | ".join(filter_parts),
        columns=['Date', 'Description', 'Category', 'Source', 'Your Share / Amount'],
        rows=rows,
        col_widths=[18, 34, 20, 26, 20],
        right_align_cols=[4],
        summary_cells=['Total', f"{len(rows)} Entries", '', '', format_inr(total_amt)],
        use_landscape=False,
        accent_hex='#4f46e5',
    )


@login_required
def export_sharing_pdf_view(request):
    """Exports Room Sharing or Trip Sharing bills (filtered by period, payer, split member, or category popup) to PDF."""
    is_viewer, target_user, target_profile, _ = _resolve_target_user(request)
    mode = request.GET.get('mode', 'room').strip().lower()
    if mode not in ['room', 'trip']:
        mode = 'room'

    today = datetime.date.today()
    period = _parse_month_year_params(request, today)
    selected_year = period['selected_year']
    selected_month = period['selected_month']
    is_full_year = period['is_full_year']
    period_label = f"Full Year {selected_year}" if is_full_year else f"{period['month_name']} {selected_year}"

    membership = SharingGroupMembership.objects.filter(
        user=target_user,
        group__group_type=mode,
        group__is_active=True
    ).select_related('group').first()

    if not membership:
        messages.error(request, f"No active {mode} sharing group found to export.")
        return redirect(f"/room-tracker/?mode={mode}")

    group = membership.group
    qs = SharedExpense.objects.filter(
        group=group,
        date__year=selected_year
    ).select_related('paid_by', 'paid_by__profile').prefetch_related('split_members').order_by('-date', '-id')
    if not is_full_year:
        qs = qs.filter(date__month=selected_month)

    paid_by_param = request.GET.get('paid_by', '').strip()
    split_with_param = request.GET.get('split_with', '').strip()
    category_param = request.GET.get('category', '').strip()

    filter_parts = [f"Group: {group.name} ({group.passkey})", f"Period: {period_label}"]
    expenses = list(qs)

    if paid_by_param and paid_by_param.lower() != 'all':
        try:
            pid = int(paid_by_param)
            expenses = [e for e in expenses if e.paid_by_id == pid]
            payer_user = User.objects.filter(id=pid).first()
            if payer_user:
                pname = payer_user.profile.display_name if hasattr(payer_user, 'profile') else payer_user.username
                filter_parts.append(f"Paid By: {pname}")
        except ValueError:
            pass

    if split_with_param and split_with_param.lower() != 'all':
        if split_with_param == 'all_members':
            expenses = [e for e in expenses if e.split_members.count() >= group.total_members]
            filter_parts.append("Split: All Members")
        else:
            try:
                sid = int(split_with_param)
                expenses = [e for e in expenses if any(s.id == sid for s in e.split_members.all())]
                suser = User.objects.filter(id=sid).first()
                if suser:
                    sname = suser.profile.display_name if hasattr(suser, 'profile') else suser.username
                    filter_parts.append(f"Split With: {sname}")
            except ValueError:
                pass

    if category_param and category_param.lower() != 'all':
        expenses = [e for e in expenses if (e.category or '').strip().lower() == category_param.lower()]
        filter_parts.append(f"Category: {category_param}")

    rows = []
    total_bill_amt = Decimal('0.00')
    for exp in expenses:
        splits = list(exp.split_members.all())
        split_count = len(splits)
        split_names = [s.profile.display_name if hasattr(s, 'profile') else s.username for s in splits]
        split_desc = "All Members" if split_count == group.total_members else ", ".join(split_names)
        payer_name = exp.paid_by.profile.display_name if hasattr(exp.paid_by, 'profile') else exp.paid_by.username
        total_bill_amt += exp.amount
        rows.append([
            exp.date.strftime('%d/%m/%Y'),
            exp.description,
            exp.category or 'Other',
            payer_name,
            split_desc,
            format_inr(exp.amount),
            format_inr(exp.per_person_share),
        ])

    mode_label = "Trip Sharing" if mode == 'trip' else "Room Sharing"
    title = f"{mode_label} ({group.name}) - {category_param}" if (category_param and category_param.lower() != 'all') else f"{mode_label} Bills History - {group.name}"
    safe_group = "".join(ch if ch.isalnum() else "_" for ch in group.name)
    filename = f"RupeeRoute_{mode_label.replace(' ', '_')}_{safe_group}_{selected_year}_{selected_month}.pdf"

    return build_pdf_response(
        filename=filename,
        title=title,
        subtitle=" | ".join(filter_parts),
        columns=['Date', 'Purpose / Description', 'Category', 'Paid By', 'Split With', 'Total Bill', 'Share / Person'],
        rows=rows,
        col_widths=[16, 28, 17, 18, 26, 17, 17],
        right_align_cols=[5, 6],
        summary_cells=['Total', f"{len(rows)} Bills", '', '', '', format_inr(total_bill_amt), '-'],
        use_landscape=True,
        accent_hex='#0f766e' if mode == 'trip' else '#4f46e5',
    )


@login_required
def export_lend_borrow_pdf_view(request):
    """Exports Lend & Borrow (Given or Taken) records with active filters to PDF."""
    is_viewer, target_user, target_profile, _ = _resolve_target_user(request)
    tab = request.GET.get('tab', 'given').strip().lower()
    if tab not in ['given', 'taken']:
        tab = 'given'

    person_query = request.GET.get('person', '').strip().lower()
    status_filter = request.GET.get('status', 'all').strip().lower()
    interest_filter = request.GET.get('interest', 'all').strip().lower()

    records = list(LoanRecord.objects.filter(user=target_user, transaction_type=tab))
    filter_parts = [
        f"Account: {target_profile.display_name}",
        "Section: Money Given (Lent)" if tab == 'given' else "Section: Money Borrowed (Taken)"
    ]

    if person_query:
        records = [r for r in records if person_query in r.person_name.lower()]
        filter_parts.append(f"Person Search: {person_query}")
    if status_filter in ['pending', 'settled']:
        records = [r for r in records if r.status == status_filter]
        filter_parts.append(f"Status: {status_filter.capitalize()}")
    if interest_filter == 'with_interest':
        records = [r for r in records if r.has_interest]
        filter_parts.append("With Interest Only")
    elif interest_filter == 'no_interest':
        records = [r for r in records if not r.has_interest]
        filter_parts.append("Without Interest")

    rows = []
    total_principal = Decimal('0.00')
    total_interest = Decimal('0.00')
    total_expected = Decimal('0.00')

    for r in records:
        total_principal += r.amount
        total_interest += r.calculated_interest
        total_expected += r.total_expected_amount
        interest_terms = f"{r.interest_rate}% / {r.interest_period} ({r.duration_value} {r.duration_unit})" if r.has_interest else "No Interest (0%)"
        expected_dt = r.expected_return_date.strftime('%d/%m/%Y') if r.expected_return_date else "-"
        rows.append([
            r.person_name + (f" ({r.phone})" if r.phone else ""),
            r.status.capitalize(),
            r.given_date.strftime('%d/%m/%Y'),
            expected_dt,
            format_inr(r.amount),
            interest_terms,
            format_inr(r.calculated_interest),
            format_inr(r.total_expected_amount),
            r.notes or '-',
        ])

    title = "Money Given (Lent) Report" if tab == 'given' else "Money Taken (Borrowed) Report"
    filename = f"RupeeRoute_LendBorrow_{tab}.pdf"

    return build_pdf_response(
        filename=filename,
        title=title,
        subtitle=" | ".join(filter_parts),
        columns=['Person', 'Status', 'Date', 'Expected Return', 'Principal', 'Interest Terms', 'Interest Amt', 'Total Return', 'Notes'],
        rows=rows,
        col_widths=[22, 12, 14, 15, 16, 22, 15, 16, 20],
        right_align_cols=[4, 6, 7],
        summary_cells=[
            'Total', f"{len(rows)} Entries", '', '',
            format_inr(total_principal), '', format_inr(total_interest), format_inr(total_expected), ''
        ],
        use_landscape=True,
        accent_hex='#0f766e' if tab == 'given' else '#dc2626',
    )


# =============================================================================
# INTERNAL SHARING NOTIFICATIONS
# =============================================================================
@login_required
def notification_click_view(request, notif_id):
    """
    Marks a notification as read (unless viewer mode) and redirects directly
    to the corresponding change in Sharing Hub.
    """
    is_viewer, target_user, _, _ = _resolve_target_user(request)
    notif = get_object_or_404(Notification, id=notif_id, recipient=target_user)
    if not is_viewer and not notif.is_read:
        notif.is_read = True
        notif.save(update_fields=['is_read'])
    return redirect(notif.target_url or 'room_tracker')


@login_required
def notifications_mark_all_read_view(request):
    """
    Marks all unread notifications for the logged-in user as read.
    """
    if request.method == 'POST':
        is_viewer, target_user, _, _ = _resolve_target_user(request)
        if not is_viewer:
            Notification.objects.filter(recipient=target_user, is_read=False).update(is_read=True)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'ok': True, 'unread_count': 0})
    return redirect(request.META.get('HTTP_REFERER') or 'analytics')

