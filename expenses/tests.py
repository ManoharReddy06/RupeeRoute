import datetime
import json
from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from .models import UserProfile, PersonalExpense, SharingGroup, SharingGroupMembership, SharedExpense, LoanRecord, Notification


class AuthTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )

    def test_anonymous_redirect(self):
        """Unauthenticated user accessing home should be redirected to login."""
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_login_success(self):
        """User can log in successfully."""
        response = self.client.post(reverse('login'), {
            'username': 'testuser',
            'password': 'password123',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['user'].is_authenticated)

    def test_login_invalid(self):
        """Invalid credentials show error."""
        response = self.client.post(reverse('login'), {
            'username': 'testuser',
            'password': 'wrongpassword',
        })
        self.assertEqual(response.status_code, 200)

    def test_login_page_hides_active_credentials_and_supports_autofill(self):
        """Login page only exposes demo user option, hides active account credentials, and includes autocomplete attrs."""
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'fillManoharBtn')
        self.assertNotContains(response, 'demo123')
        self.assertNotContains(response, 'Fill Active Tracker Demo')
        self.assertContains(response, 'fillAdminBtn')
        self.assertContains(response, 'autocomplete="username"')
        self.assertContains(response, 'autocomplete="current-password"')

    def test_registration(self):
        """New user can register and profile is created with is_profile_setup=False."""
        response = self.client.post(reverse('register'), {
            'username': 'brandnewuser',
            'email': 'new@example.com',
            'password': 'safePassword123',
            'confirm_password': 'safePassword123',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(username='brandnewuser').exists())
        self.assertTrue(response.context['user'].is_authenticated)
        # Verify UserProfile was created
        profile = UserProfile.objects.get(user__username='brandnewuser')
        self.assertFalse(profile.is_profile_setup)

    def test_logout(self):
        """Logged in user can log out."""
        self.client.login(username='testuser', password='password123')
        response = self.client.get(reverse('logout'), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['user'].is_authenticated)


class ProfileSetupTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='manohar',
            password='secretpassword'
        )
        self.profile = UserProfile.objects.create(
            user=self.user,
            is_profile_setup=False
        )
        self.client.login(username='manohar', password='secretpassword')

    def test_first_time_login_shows_profile_setup(self):
        """First time user who has not set up profile sees Profile Setup page."""
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'expenses/profile_setup.html')
        self.assertContains(response, 'Complete Your Profile')

    def test_complete_profile_setup(self):
        """Submitting full name and age completes setup and redirects to tracker dashboard."""
        response = self.client.post(reverse('home'), {
            'full_name': 'Manohar Anreddy',
            'age': 25,
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'expenses/dashboard.html')

        # Verify profile updated in DB
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.is_profile_setup)
        self.assertEqual(self.profile.full_name, 'Manohar Anreddy')
        self.assertEqual(self.profile.age, 25)
        self.assertEqual(self.profile.initials, 'MA')

        # Verify dashboard renders profile card and current month expense field
        self.assertContains(response, 'Manohar Anreddy')
        self.assertContains(response, 'Age: 25 years old')
        self.assertContains(response, 'Current Month Expense')


class PersonalExpenseTrackerTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='trackeruser',
            password='trackerpass'
        )
        self.profile = UserProfile.objects.create(
            user=self.user,
            full_name='Saiteja Sharma',
            age=26,
            is_profile_setup=True
        )
        self.client.login(username='trackeruser', password='trackerpass')

    def test_dashboard_empty_state(self):
        """When no expenses logged, dashboard shows zero total and empty message."""
        response = self.client.get(reverse('home') + '?month=11&year=2026')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'expenses/dashboard.html')
        self.assertContains(response, '₹0.00')
        self.assertContains(response, 'No past entries found')

    def test_add_expense_and_recalculation(self):
        """
        Adding an expense recalculates:
        1. Top Profile Card current month expense
        2. Category breakdown tab
        3. Past entries history table
        """
        # Add Curd under Food/Curd for ₹50 on 10/11/2026
        response = self.client.post(reverse('add_expense'), {
            'date': '2026-11-10',
            'description': 'Curd',
            'category': 'Food/Curd',
            'amount': '50.00'
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'expenses/dashboard.html')

        # Check expense was saved
        expense = PersonalExpense.objects.get(description='Curd')
        self.assertEqual(expense.amount, Decimal('50.00'))
        self.assertEqual(expense.category, 'Food/Curd')
        self.assertEqual(expense.date, datetime.date(2026, 11, 10))

        # Check page contains recalculated amount and breakdown
        self.assertContains(response, '₹50.00')
        self.assertContains(response, 'Food/Curd')
        self.assertContains(response, '10/11/2026')

        # Add second expense: Rapido under Travel for ₹120 on 12/11/2026
        response2 = self.client.post(reverse('add_expense'), {
            'date': '2026-11-12',
            'description': 'Rapido',
            'category': 'Travel',
            'amount': '120.00'
        }, follow=True)

        self.assertEqual(response2.status_code, 200)
        # Total should now be 50 + 120 = 170.00
        self.assertContains(response2, '₹170.00')
        self.assertContains(response2, 'Travel')
        self.assertContains(response2, 'Food/Curd')

    def test_delete_expense(self):
        """Deleting an expense recalculates total spent."""
        exp = PersonalExpense.objects.create(
            user=self.user,
            date=datetime.date(2026, 11, 10),
            description='Curd',
            category='Food/Curd',
            amount=Decimal('50.00')
        )
        # Verify it exists
        self.assertEqual(PersonalExpense.objects.count(), 1)

        # Delete it
        del_response = self.client.post(
            reverse('delete_expense', kwargs={'expense_id': exp.id}),
            follow=True
        )
        self.assertEqual(del_response.status_code, 200)
        self.assertEqual(PersonalExpense.objects.count(), 0)
        self.assertContains(del_response, '₹0.00')

    def test_month_year_filter_isolation(self):
        """Expenses from different months do not bleed into current month."""
        # November 2026 expense
        PersonalExpense.objects.create(
            user=self.user,
            date=datetime.date(2026, 11, 15),
            description='November Rent',
            category='Rent',
            amount=Decimal('8000.00')
        )
        # October 2026 expense
        PersonalExpense.objects.create(
            user=self.user,
            date=datetime.date(2026, 10, 15),
            description='October Rent',
            category='Rent',
            amount=Decimal('7500.00')
        )

        # Check November 2026 view
        nov_resp = self.client.get(reverse('home') + '?month=11&year=2026')
        self.assertContains(nov_resp, '₹8000.00')
        self.assertNotContains(nov_resp, '₹7500.00')
        self.assertContains(nov_resp, 'November Rent')
        self.assertNotContains(nov_resp, 'October Rent')

        # Check October 2026 view
        oct_resp = self.client.get(reverse('home') + '?month=10&year=2026')
        self.assertContains(oct_resp, '₹7500.00')
        self.assertNotContains(oct_resp, '₹8000.00')
        self.assertContains(oct_resp, 'October Rent')
        self.assertNotContains(oct_resp, 'November Rent')

    def test_yearly_expense_aggregation_and_full_year_view(self):
        """
        User can check total 2026 year expense:
        1. In month view, Total Year Spend is visible on the profile card.
        2. Selecting 'All Months (Full Year)' shows all 2026 transactions combined.
        """
        # Create expenses across different months of 2026
        PersonalExpense.objects.create(
            user=self.user,
            date=datetime.date(2026, 10, 15),
            description='October Rent',
            category='Rent',
            amount=Decimal('7500.00')
        )
        PersonalExpense.objects.create(
            user=self.user,
            date=datetime.date(2026, 11, 10),
            description='Curd',
            category='Food/Curd',
            amount=Decimal('50.00')
        )
        PersonalExpense.objects.create(
            user=self.user,
            date=datetime.date(2026, 11, 15),
            description='November Rent',
            category='Rent',
            amount=Decimal('8000.00')
        )

        # Total 2026 = 7500 + 50 + 8000 = 15550.00
        # Check Month View (November 2026) shows Month (8050.00) AND Total Year Spend (15550.00)
        month_resp = self.client.get(reverse('home') + '?month=11&year=2026')
        self.assertContains(month_resp, '₹8050.00') # Month
        self.assertContains(month_resp, '₹15550.00') # Total Year Spend
        self.assertContains(month_resp, 'Total Year Spend (2026)')

        # Check Full Year View (?month=0&year=2026)
        full_year_resp = self.client.get(reverse('home') + '?month=0&year=2026')
        self.assertEqual(full_year_resp.status_code, 200)
        self.assertContains(full_year_resp, 'Full Year 2026')
        self.assertContains(full_year_resp, '₹15550.00')
        self.assertContains(full_year_resp, 'October Rent')
        self.assertContains(full_year_resp, 'November Rent')
        self.assertContains(full_year_resp, 'Curd')
        # Category breakdown contains aggregated Rent = 7500 + 8000 = 15500.00
        self.assertContains(full_year_resp, '₹15500.00')

    def test_category_filter_and_modal_data(self):
        """
        Clicking on a category filters spents and loads category details:
        1. Querying with ?category=Rent only displays Rent spents in the history table.
        2. Category JSON data block contains items for the category modal.
        """
        PersonalExpense.objects.create(
            user=self.user,
            date=datetime.date(2026, 11, 1),
            description='November Room Rent',
            category='Rent',
            amount=Decimal('8000.00')
        )
        PersonalExpense.objects.create(
            user=self.user,
            date=datetime.date(2026, 11, 10),
            description='Curd Packet',
            category='Food/Curd',
            amount=Decimal('50.00')
        )
        PersonalExpense.objects.create(
            user=self.user,
            date=datetime.date(2026, 11, 12),
            description='Rapido Ride',
            category='Travel',
            amount=Decimal('120.00')
        )

        # Filter by Rent
        response = self.client.get(reverse('home') + '?month=11&year=2026&category=Rent')
        self.assertEqual(response.status_code, 200)

        # Context expenses should only contain Rent
        expenses_in_table = list(response.context['expenses'])
        self.assertEqual(len(expenses_in_table), 1)
        self.assertEqual(expenses_in_table[0].description, 'November Room Rent')
        self.assertEqual(expenses_in_table[0].category, 'Rent')

        # Categories JSON data block is present for modal popup
        self.assertContains(response, 'categoriesJsonData')
        self.assertContains(response, 'categoryHistoryModal')

    def test_history_filters_date_and_amount(self):
        """
        User can filter past entries by particular date and amount range:
        1. Filtering by specific date returns only spents on that date.
        2. Filtering by amount range returns only spents within min/max bounds.
        3. Filter toolbar inputs are present above the table.
        """
        PersonalExpense.objects.create(
            user=self.user,
            date=datetime.date(2026, 11, 1),
            description='November Room Rent',
            category='Rent',
            amount=Decimal('8000.00')
        )
        PersonalExpense.objects.create(
            user=self.user,
            date=datetime.date(2026, 11, 10),
            description='Curd Packet',
            category='Food/Curd',
            amount=Decimal('50.00')
        )
        PersonalExpense.objects.create(
            user=self.user,
            date=datetime.date(2026, 11, 12),
            description='Rapido Ride',
            category='Travel',
            amount=Decimal('120.00')
        )

        # 1. Filter by specific date (2026-11-10)
        date_resp = self.client.get(reverse('home') + '?month=11&year=2026&date=2026-11-10')
        self.assertEqual(date_resp.status_code, 200)
        date_expenses = list(date_resp.context['expenses'])
        self.assertEqual(len(date_expenses), 1)
        self.assertEqual(date_expenses[0].description, 'Curd Packet')

        # 2. Filter by amount range: Min ₹100, Max ₹1000
        amt_resp = self.client.get(reverse('home') + '?month=11&year=2026&min_amount=100&max_amount=1000')
        self.assertEqual(amt_resp.status_code, 200)
        amt_expenses = list(amt_resp.context['expenses'])
        self.assertEqual(len(amt_expenses), 1)
        self.assertEqual(amt_expenses[0].description, 'Rapido Ride')
        self.assertEqual(amt_expenses[0].amount, Decimal('120.00'))

        # 3. Verify Filter Toolbar elements are rendered in HTML
        self.assertContains(amt_resp, 'history-filters-toolbar')
        self.assertContains(amt_resp, 'id="historyFilterDate"')
        self.assertContains(amt_resp, 'id="historyFilterCategory"')
        self.assertContains(amt_resp, 'id="historyFilterMinAmount"')
        self.assertContains(amt_resp, 'id="historyFilterMaxAmount"')

    def test_edit_expense(self):
        """
        Editing an existing expense:
        1. Submitting new date, description, category, and amount updates the record.
        2. Recalculates total spent and breakdown.
        """
        exp = PersonalExpense.objects.create(
            user=self.user,
            date=datetime.date(2026, 11, 10),
            description='Curd Small',
            category='Food/Curd',
            amount=Decimal('40.00')
        )

        # Edit the expense to Curd Family Pack for ₹80
        edit_resp = self.client.post(
            reverse('edit_expense', kwargs={'expense_id': exp.id}),
            {
                'date': '2026-11-10',
                'description': 'Curd Family Pack',
                'category': 'Food/Curd',
                'amount': '80.00'
            },
            follow=True
        )

        self.assertEqual(edit_resp.status_code, 200)
        exp.refresh_from_db()
        self.assertEqual(exp.description, 'Curd Family Pack')
        self.assertEqual(exp.amount, Decimal('80.00'))
        self.assertContains(edit_resp, 'Curd Family Pack')
        self.assertContains(edit_resp, '₹80.00')

    def test_per_field_clear_buttons_and_edit_action(self):
        """
        Verify per-field X clear buttons, search button, category modal, and Edit action button are rendered in the dashboard.
        """
        PersonalExpense.objects.create(
            user=self.user,
            date=datetime.date(2026, 11, 10),
            description='Curd Packet',
            category='Food/Curd',
            amount=Decimal('50.00')
        )
        response = self.client.get(reverse('home') + '?month=11&year=2026')
        self.assertEqual(response.status_code, 200)

        # 1. Verify per-field X clear buttons exist
        self.assertContains(response, 'id="clearDateBtn"')
        self.assertContains(response, 'id="clearCategoryBtn"')
        self.assertContains(response, 'id="clearAmountBtn"')

        # 2. Verify Search Button and Reset All Button exist
        self.assertContains(response, 'id="searchFiltersBtn"')
        self.assertContains(response, 'id="resetAllFiltersBtn"')

        # 3. Verify Category Details Popup Modal exists
        self.assertContains(response, 'id="categoryHistoryModal"')
        self.assertContains(response, 'id="modalCategoryTitle"')
        self.assertContains(response, 'id="modalCategoryTableBody"')
        self.assertContains(response, 'openCategoryDetails')

        # 4. Verify Category Breakdown JSON is present and valid
        self.assertIn('category_breakdown_json', response.context)
        breakdown_data = json.loads(response.context['category_breakdown_json'])
        self.assertEqual(len(breakdown_data), 1)
        self.assertEqual(breakdown_data[0]['name'], 'Food/Curd')
        self.assertEqual(len(breakdown_data[0]['items']), 1)
        self.assertEqual(breakdown_data[0]['items'][0]['description'], 'Curd Packet')

        # 5. Verify Edit button and Edit Modal are rendered
        self.assertContains(response, 'class="btn-edit"')
        self.assertContains(response, 'openEditExpenseModal')
        self.assertContains(response, 'id="editExpenseModal"')
        self.assertContains(response, 'id="editExpenseForm"')







class NewNavigationAndFeaturesTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testnavuser',
            password='testnavpass'
        )
        self.profile = UserProfile.objects.create(
            user=self.user,
            full_name='Nav User',
            age=27,
            is_profile_setup=True
        )
        self.client.login(username='testnavuser', password='testnavpass')

    def test_room_tracker_page(self):
        """Sharing Hub page should display 'Sharing'."""
        response = self.client.get(reverse('room_tracker'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Sharing')
        self.assertEqual(response.context['current_tracker'], 'sharing')

    def test_sidebar_rendered_with_both_trackers(self):
        """Sidebar must have Personal Tracker and Sharing below logo."""
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Personal Tracker')
        self.assertContains(response, 'Sharing')
        self.assertContains(response, 'id="appSidebar"')

    def test_three_line_menu_rendered(self):
        """Three line menu button, username, update profile and logout must be rendered."""
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="threeLineBtn"')
        self.assertContains(response, 'testnavuser')
        self.assertContains(response, 'Update Profile')
        self.assertContains(response, reverse('update_profile'))
        self.assertContains(response, reverse('logout'))

    def test_update_profile_view(self):
        """User can view and submit updated profile."""
        get_resp = self.client.get(reverse('update_profile'))
        self.assertEqual(get_resp.status_code, 200)
        self.assertContains(get_resp, 'Update Profile')

        post_resp = self.client.post(reverse('update_profile'), {
            'full_name': 'Updated Nav Name',
            'age': 30,
        }, follow=True)
        self.assertEqual(post_resp.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.full_name, 'Updated Nav Name')
        self.assertEqual(self.profile.age, 30)

    def test_edit_modal_category_select(self):
        """Edit modal should render category select with all categories."""
        PersonalExpense.objects.create(
            user=self.user,
            date=datetime.date(2026, 11, 1),
            description='Test Snack',
            category='Food',
            amount=Decimal('25.00')
        )
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="editCategorySelect"')
        self.assertContains(response, 'Food')
        self.assertContains(response, 'Travel')
        self.assertContains(response, 'Rent')
        self.assertContains(response, 'Shopping')
        self.assertContains(response, 'Recharge')


class ViewerProfileAndPermissionsTests(TestCase):
    def setUp(self):
        self.client = Client()
        # Create Super Admin / Owner User
        self.admin_user = User.objects.create_user(
            username='adminuser',
            email='admin@example.com',
            password='adminpassword123'
        )
        self.admin_profile = UserProfile.objects.create(
            user=self.admin_user,
            full_name='Admin Owner',
            age=29,
            is_profile_setup=True,
            is_viewer=False
        )

        # Create an expense for the Admin
        self.admin_expense = PersonalExpense.objects.create(
            user=self.admin_user,
            date=datetime.date(2026, 11, 15),
            description='Admin Office Lunch',
            category='Food',
            amount=Decimal('150.00')
        )

        # Login as Admin
        self.client.login(username='adminuser', password='adminpassword123')

    def test_admin_can_access_create_viewer_page(self):
        """Admin can access the Create Viewer page."""
        response = self.client.get(reverse('create_viewer'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create Viewer Profile')
        self.assertContains(response, 'Add New Viewer Account')

    def test_admin_creates_viewer_successfully(self):
        """Admin creates a viewer profile with username and password."""
        response = self.client.post(reverse('create_viewer'), {
            'full_name': 'Dad Viewer',
            'username': 'familyviewer',
            'password': 'viewerPass@123',
            'confirm_password': 'viewerPass@123',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'familyviewer')
        self.assertContains(response, 'Dad Viewer')

        # Verify Viewer user in DB
        viewer_user = User.objects.filter(username='familyviewer').first()
        self.assertIsNotNone(viewer_user)
        self.assertTrue(viewer_user.profile.is_viewer)
        self.assertEqual(viewer_user.profile.viewer_of, self.admin_user)
        self.assertEqual(viewer_user.profile.full_name, 'Dad Viewer')

    def test_viewer_sees_admin_dashboard_in_readonly_mode(self):
        """When viewer logs in, they see the admin's dashboard and expenses in read-only mode."""
        # Create viewer
        viewer_user = User.objects.create_user(
            username='viewerfriend',
            email='viewerfriend@example.com',
            password='secretpassword'
        )
        UserProfile.objects.create(
            user=viewer_user,
            full_name='Friend Viewer',
            is_profile_setup=True,
            is_viewer=True,
            viewer_of=self.admin_user
        )

        # Login as viewer
        self.client.login(username='viewerfriend', password='secretpassword')
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)

        # Viewer sees Admin's name and expense
        self.assertContains(response, 'Admin Owner')
        self.assertContains(response, 'Admin Office Lunch')
        self.assertContains(response, '150.00')
        self.assertContains(response, 'Viewer Mode')

        # Viewer CANNOT see the add or edit or delete buttons or Create Viewer in sidebar
        self.assertNotContains(response, 'Enter New Spents')
        self.assertNotContains(response, 'class="btn-edit"')
        self.assertNotContains(response, 'class="btn-delete"')
        self.assertNotContains(response, 'Create Viewer')

    def test_viewer_cannot_add_edit_or_delete_expense(self):
        """Viewer cannot POST to add, edit, or delete endpoints."""
        viewer_user = User.objects.create_user(
            username='readonlyviewer',
            password='secretpassword'
        )
        UserProfile.objects.create(
            user=viewer_user,
            is_profile_setup=True,
            is_viewer=True,
            viewer_of=self.admin_user
        )
        self.client.login(username='readonlyviewer', password='secretpassword')

        # 1. Try to add expense
        add_resp = self.client.post(reverse('add_expense'), {
            'date': '2026-11-15',
            'description': 'Hacked Spent',
            'category': 'Food',
            'amount': '999.00'
        }, follow=True)
        self.assertEqual(add_resp.status_code, 200)
        self.assertFalse(PersonalExpense.objects.filter(description='Hacked Spent').exists())

        # 2. Try to edit expense
        edit_resp = self.client.post(reverse('edit_expense', kwargs={'expense_id': self.admin_expense.id}), {
            'date': '2026-11-15',
            'description': 'Tampered Spent',
            'category': 'Food',
            'amount': '1.00'
        }, follow=True)
        self.assertEqual(edit_resp.status_code, 200)
        self.admin_expense.refresh_from_db()
        self.assertEqual(self.admin_expense.description, 'Admin Office Lunch')
        self.assertEqual(self.admin_expense.amount, Decimal('150.00'))

        # 3. Try to delete expense
        del_resp = self.client.post(reverse('delete_expense', kwargs={'expense_id': self.admin_expense.id}), follow=True)
        self.assertEqual(del_resp.status_code, 200)
        self.assertTrue(PersonalExpense.objects.filter(id=self.admin_expense.id).exists())

    def test_admin_can_revoke_viewer(self):
        """Admin can revoke viewer access."""
        viewer_user = User.objects.create_user(
            username='revokeme',
            password='secretpassword'
        )
        UserProfile.objects.create(
            user=viewer_user,
            is_profile_setup=True,
            is_viewer=True,
            viewer_of=self.admin_user
        )

        response = self.client.post(reverse('delete_viewer', kwargs={'viewer_id': viewer_user.id}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='revokeme').exists())

    def test_create_viewer_page_has_note(self):
        """Create viewer page renders cleanly with NOTE component."""
        self.client.login(username='adminowner', password='secretpassword')
        response = self.client.get(reverse('create_viewer'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'NOTE:')
        self.assertContains(response, 'viewer-note-box')

    def test_split_expense_across_three_months(self):
        """Entering ₹5,000 split across 3 months creates 3 installments summing to ₹5,000."""
        self.client.login(username='adminowner', password='secretpassword')

        post_data = {
            'date': '2026-11-19',
            'amount': '5000.00',
            'description': 'Gym Membership',
            'category': 'Other',
            'is_split': 'true',
            'split_months': '3',
        }
        response = self.client.post(reverse('add_expense'), post_data, follow=True)
        self.assertEqual(response.status_code, 200)

        # Verify 3 expenses were created for adminowner
        gym_expenses = PersonalExpense.objects.filter(
            user=self.admin_user,
            description__startswith='Gym Membership'
        ).order_by('date')
        self.assertEqual(gym_expenses.count(), 3)

        # Check dates and amounts
        e1, e2, e3 = gym_expenses
        self.assertEqual(e1.date, datetime.date(2026, 11, 19))
        self.assertEqual(e2.date, datetime.date(2026, 12, 19))
        self.assertEqual(e3.date, datetime.date(2027, 1, 19))

        # Check total sums up exactly to 5000.00
        total_split = e1.amount + e2.amount + e3.amount
        self.assertEqual(total_split, Decimal('5000.00'))

        # Check description suffixes
        self.assertIn('Split 1/3 - Nov', e1.description)
        self.assertIn('Split 2/3 - Dec', e2.description)
        self.assertIn('Split 3/3 - Jan', e3.description)

        # Verify each month's dashboard shows its respective installment
        nov_resp = self.client.get(f"{reverse('home')}?month=11&year=2026")
        self.assertContains(nov_resp, 'Split 1/3 - Nov')

        dec_resp = self.client.get(f"{reverse('home')}?month=12&year=2026")
        self.assertContains(dec_resp, 'Split 2/3 - Dec')

        jan_resp = self.client.get(f"{reverse('home')}?month=1&year=2027")
        self.assertContains(jan_resp, 'Split 3/3 - Jan')


class SharingGroupTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user1 = User.objects.create_user(username='manohar', password='secretpassword')
        self.profile1 = UserProfile.objects.create(
            user=self.user1,
            full_name='Manohar Anreddy',
            is_profile_setup=True
        )
        self.user2 = User.objects.create_user(username='roommate1', password='secretpassword')
        self.profile2 = UserProfile.objects.create(
            user=self.user2,
            full_name='Alex Roommate',
            is_profile_setup=True
        )
        self.user3 = User.objects.create_user(username='roommate2', password='secretpassword')
        self.profile3 = UserProfile.objects.create(
            user=self.user3,
            full_name='Bob Roommate',
            is_profile_setup=True
        )

        today = datetime.date.today()
        PersonalExpense.objects.create(
            user=self.user1,
            date=today,
            amount=Decimal('4500.00'),
            description='Manohar Food'
        )
        PersonalExpense.objects.create(
            user=self.user2,
            date=today,
            amount=Decimal('2200.00'),
            description='Alex Groceries'
        )

    def test_sharing_page_renders_sidebar_and_toggles(self):
        """Sharing page renders with 'Sharing' in sidebar, clean top tabs, and NO profile cards shown initially."""
        self.client.login(username='manohar', password='secretpassword')
        response = self.client.get(reverse('room_tracker'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Sharing')
        self.assertContains(response, 'Room Sharing')
        self.assertContains(response, 'Trip Sharing')
        self.assertContains(response, 'sharing-hub__landing')
        self.assertContains(response, 'sharing-card-btn--room')
        self.assertContains(response, 'sharing-card-btn--trip')
        # Crucial check: Profile card is NOT visible before joining or creating!
        self.assertNotContains(response, 'profile-card')
        self.assertNotContains(response, 'Member Slot')

    def test_create_room_sharing_group_with_three_members(self):
        """User creates a room group with 3 members; passkey is generated; shows 1 user card & 2 empty slots."""
        from .models import SharingGroup
        self.client.login(username='manohar', password='secretpassword')
        create_resp = self.client.post(reverse('create_sharing_group'), {
            'group_type': 'room',
            'total_members': '3',
            'name': 'Apartment 302',
        }, follow=True)
        self.assertEqual(create_resp.status_code, 200)

        group = SharingGroup.objects.get(name='Apartment 302', group_type='room')
        self.assertEqual(group.total_members, 3)
        self.assertTrue(group.passkey.startswith('ROOM-'))
        self.assertEqual(group.creator, self.user1)

        # Verify page shows passkey, user's card, and 2 empty slots
        view_resp = self.client.get(f"{reverse('room_tracker')}?toggle=room")
        self.assertContains(view_resp, group.passkey)
        self.assertContains(view_resp, 'Manohar Anreddy')
        self.assertContains(view_resp, '4500.00')  # monthly spent
        self.assertContains(view_resp, 'Roommate Slot #2 (Waiting to Join)')
        self.assertContains(view_resp, 'Roommate Slot #3 (Waiting to Join)')

    def test_roommate_joins_using_passkey_shows_both_profile_cards(self):
        """Roommate enters passkey, joins group, and both cards appear with Monthly Spent and Monthly Average."""
        from .models import SharingGroup, SharingGroupMembership
        # 1. User 1 creates group
        group = SharingGroup.objects.create(
            group_type='room',
            name='Flat 401',
            passkey='ROOM-8888',
            total_members=3,
            creator=self.user1
        )
        SharingGroupMembership.objects.create(group=group, user=self.user1, role='creator')

        # 2. User 2 logs in and joins with passkey
        self.client.login(username='roommate1', password='secretpassword')
        join_resp = self.client.post(reverse('join_sharing_group'), {
            'passkey': 'ROOM-8888',
            'group_type': 'room'
        }, follow=True)
        self.assertEqual(join_resp.status_code, 200)
        self.assertTrue(SharingGroupMembership.objects.filter(group=group, user=self.user2).exists())

        # Verify user 2 sees both cards: Manohar & Alex
        view_resp = self.client.get(f"{reverse('room_tracker')}?toggle=room")
        self.assertContains(view_resp, 'ROOM-8888')
        self.assertContains(view_resp, 'Manohar Anreddy')
        self.assertContains(view_resp, 'Alex Roommate')
        self.assertContains(view_resp, '4500.00')
        self.assertContains(view_resp, '2200.00')
        # Only 1 slot remains empty (slot 3)
        self.assertContains(view_resp, 'Roommate Slot #3 (Waiting to Join)')
        self.assertNotContains(view_resp, 'Roommate Slot #2 (Waiting to Join)')

    def test_room_sharing_full_group_capacity(self):
        """When 2 members have joined, 3rd member cannot join."""
        from .models import SharingGroup, SharingGroupMembership
        group = SharingGroup.objects.create(
            group_type='room',
            name='Full Flat',
            passkey='ROOM-9999',
            total_members=2,
            creator=self.user1
        )
        SharingGroupMembership.objects.create(group=group, user=self.user1, role='creator')
        SharingGroupMembership.objects.create(group=group, user=self.user2, role='member')

        # User 3 tries to join full group
        self.client.login(username='roommate2', password='secretpassword')
        join_resp = self.client.post(reverse('join_sharing_group'), {
            'passkey': 'ROOM-9999',
            'group_type': 'room'
        }, follow=True)
        self.assertEqual(join_resp.status_code, 200)
        self.assertFalse(SharingGroupMembership.objects.filter(group=group, user=self.user3).exists())

    def test_add_shared_expense_and_balance_calculation(self):
        """Roommates can add a shared bill; verify per-head split, balance, category breakdown, and history."""
        from .models import SharingGroup, SharingGroupMembership, SharedExpense
        group = SharingGroup.objects.create(
            group_type='room',
            name='Luxury Suite',
            passkey='ROOM-7777',
            total_members=3,
            creator=self.user1
        )
        SharingGroupMembership.objects.create(group=group, user=self.user1, role='creator')
        SharingGroupMembership.objects.create(group=group, user=self.user2, role='member')
        SharingGroupMembership.objects.create(group=group, user=self.user3, role='member')

        # User 1 logs in and adds a ₹6,000 Rent bill split among all 3 members
        self.client.login(username='manohar', password='secretpassword')
        add_resp = self.client.post(reverse('add_shared_expense'), {
            'group_id': group.id,
            'date': '2026-11-01',
            'category': 'Rent',
            'description': 'Flat Rent November',
            'amount': '6000.00',
            'paid_by': self.user1.id,
            'split_members': [self.user1.id, self.user2.id, self.user3.id],
        }, follow=True)
        self.assertEqual(add_resp.status_code, 200)

        # Verify SharedExpense created
        self.assertEqual(SharedExpense.objects.filter(group=group).count(), 1)
        exp = SharedExpense.objects.get(group=group)
        self.assertEqual(exp.amount, Decimal('6000.00'))
        self.assertEqual(exp.split_members.count(), 3)
        self.assertEqual(exp.per_person_share, Decimal('2000.00'))

        # Check Sharing page view: Category Breakdown, History Table, and Balance Badges
        view_resp = self.client.get(f"{reverse('room_tracker')}?mode=room")
        self.assertContains(view_resp, 'Room Expense Breakdown')
        self.assertContains(view_resp, 'Shared Bills History')
        self.assertContains(view_resp, 'Flat Rent November')
        self.assertContains(view_resp, '6000.00')
        self.assertContains(view_resp, '2000.00')
        # Manohar paid 6000, share 2000 -> Extra 4000
        self.assertContains(view_resp, 'Extra (Gets back)')
        # Alex and Sam paid 0, share 2000 -> Short 2000
        self.assertContains(view_resp, 'Short (Owes)')

    def test_partial_split_and_delete_shared_expense(self):
        """A bill split between only 2 members, followed by bill deletion."""
        from .models import SharingGroup, SharingGroupMembership, SharedExpense
        group = SharingGroup.objects.create(
            group_type='room',
            name='Cozy Villa',
            passkey='ROOM-6666',
            total_members=3,
            creator=self.user1
        )
        SharingGroupMembership.objects.create(group=group, user=self.user1, role='creator')
        SharingGroupMembership.objects.create(group=group, user=self.user2, role='member')
        SharingGroupMembership.objects.create(group=group, user=self.user3, role='member')

        self.client.login(username='roommate1', password='secretpassword')
        add_resp = self.client.post(reverse('add_shared_expense'), {
            'group_id': group.id,
            'date': '2026-11-05',
            'category': 'Food & Dining',
            'description': 'KFC Dinner',
            'amount': '800.00',
            'paid_by': self.user2.id,
            'split_members': [self.user1.id, self.user2.id],  # only 2 members split
        }, follow=True)
        self.assertEqual(add_resp.status_code, 200)

        exp = SharedExpense.objects.get(group=group)
        self.assertEqual(exp.split_members.count(), 2)
        self.assertEqual(exp.per_person_share, Decimal('400.00'))

        # Delete expense
        del_resp = self.client.post(reverse('delete_shared_expense', args=[exp.id]), follow=True)
        self.assertEqual(del_resp.status_code, 200)
        self.assertEqual(SharedExpense.objects.filter(group=group).count(), 0)

    def test_edit_shared_expense_visible_to_creator_only_and_updates_successfully(self):
        """Edit button appears only to the person who entered/paid the bill; editing updates all totals."""
        from .models import SharingGroup, SharingGroupMembership, SharedExpense
        group = SharingGroup.objects.create(
            group_type='room',
            name='Silicon Heights',
            passkey='ROOM-5555',
            total_members=3,
            creator=self.user1
        )
        SharingGroupMembership.objects.create(group=group, user=self.user1, role='creator')
        SharingGroupMembership.objects.create(group=group, user=self.user2, role='member')
        SharingGroupMembership.objects.create(group=group, user=self.user3, role='member')

        # User 1 logs in and adds a ₹1500 bill
        self.client.login(username='manohar', password='secretpassword')
        self.client.post(reverse('add_shared_expense'), {
            'group_id': group.id,
            'date': '2026-11-22',
            'category': 'Groceries',
            'description': 'DSL mall',
            'amount': '1500.00',
            'paid_by': self.user1.id,
            'split_members': [self.user1.id, self.user2.id, self.user3.id],
        }, follow=True)

        exp = SharedExpense.objects.get(group=group, description='DSL mall')

        # 1. User 1 views page: sees edit button
        user1_view = self.client.get(f"{reverse('room_tracker')}?mode=room")
        self.assertContains(user1_view, 'btn-edit')
        self.assertContains(user1_view, f"openEditSharedExpenseModal('room', {exp.id}")

        # 2. User 2 logs in: does NOT see edit button for User 1's bill
        self.client.login(username='roommate1', password='secretpassword')
        user2_view = self.client.get(f"{reverse('room_tracker')}?mode=room")
        self.assertNotContains(user2_view, f"openEditSharedExpenseModal('room', {exp.id}")

        # 3. User 2 attempts to edit User 1's bill -> permission denied
        hack_resp = self.client.post(reverse('edit_shared_expense', args=[exp.id]), {
            'date': '2026-11-22',
            'category': 'Groceries',
            'description': 'Hacked Bill',
            'amount': '9999.00',
            'paid_by': self.user2.id,
            'split_members': [self.user1.id, self.user2.id],
        }, follow=True)
        self.assertContains(hack_resp, "Permission denied")
        exp.refresh_from_db()
        self.assertEqual(exp.amount, Decimal('1500.00'))

        # 4. User 1 logs back in and successfully edits the bill
        self.client.login(username='manohar', password='secretpassword')
        edit_resp = self.client.post(reverse('edit_shared_expense', args=[exp.id]), {
            'date': '2026-11-22',
            'category': 'Groceries',
            'description': 'DSL mall Dmart & Groceries',
            'amount': '1800.00',
            'paid_by': self.user1.id,
            'split_members': [self.user1.id, self.user2.id, self.user3.id],
        }, follow=True)
        self.assertEqual(edit_resp.status_code, 200)

        exp.refresh_from_db()
        self.assertEqual(exp.amount, Decimal('1800.00'))
        self.assertEqual(exp.description, 'DSL mall Dmart & Groceries')
        self.assertEqual(exp.per_person_share, Decimal('600.00'))

    def test_delete_permission_and_scenario_breakdown_and_custom_category(self):
        """
        Verify:
        1. Only bill creator or payer can delete the bill; unauthorized roommate gets error and cannot delete.
        2. Filter toolbar (Paid By, Split With, Category) rendered in room sharing view.
        3. Detailed subgroup scenario breakdowns (ABC, AB, AC, etc.) are computed and present in context.
        4. Category popup modal (#sharedCategoryHistoryModal) and split breakdown modal (#memberSplitBreakdownModal) are rendered.
        5. Profile cards are rendered with metric onclick to open split breakdown modal.
        """
        # 1. Setup 3-member room group
        group = SharingGroup.objects.create(
            name="Alpha Room",
            group_type="room",
            total_members=3,
            passkey="TEST-ABC1",
            creator=self.user1
        )
        SharingGroupMembership.objects.create(group=group, user=self.user1, role="creator")
        SharingGroupMembership.objects.create(group=group, user=self.user2, role="member")
        SharingGroupMembership.objects.create(group=group, user=self.user3, role="member")

        # 2. Add Bill 1 (ABC scenario): ₹3000 paid by User 1 (Manohar), split among all 3
        exp1 = SharedExpense.objects.create(
            group=group,
            created_by=self.user1,
            paid_by=self.user1,
            date=datetime.date(2026, 11, 20),
            amount=Decimal('3000.00'),
            category='Groceries',
            description='Monthly Dmart'
        )
        exp1.split_members.set([self.user1, self.user2, self.user3])

        # Add Bill 2 (AB scenario): ₹1000 paid by User 2 (Alex), split between User 1 and User 2
        exp2 = SharedExpense.objects.create(
            group=group,
            created_by=self.user2,
            paid_by=self.user2,
            date=datetime.date(2026, 11, 21),
            amount=Decimal('1000.00'),
            category='Snacks & Drinks',
            description='Evening Party'
        )
        exp2.split_members.set([self.user1, self.user2])

        # 3. User 2 (Alex) attempts to delete exp1 (created and paid by Manohar)
        self.client.login(username='roommate1', password='secretpassword')
        unauth_del_resp = self.client.post(reverse('delete_shared_expense', args=[exp1.id]), follow=True)
        self.assertContains(unauth_del_resp, "Permission denied")
        self.assertTrue(SharedExpense.objects.filter(id=exp1.id).exists(), "Bill 1 must not be deleted by unauthorized roommate")

        # Verify User 2's room page: exp1 can_delete is False, exp2 can_delete is True
        resp_user2 = self.client.get(reverse('room_tracker') + '?mode=room')
        self.assertEqual(resp_user2.status_code, 200)

        # In context for User 2:
        room_ctx = resp_user2.context['room_group']
        exp1_ctx = next(e for e in room_ctx['expenses_history'] if e['id'] == exp1.id)
        exp2_ctx = next(e for e in room_ctx['expenses_history'] if e['id'] == exp2.id)
        self.assertFalse(exp1_ctx['can_delete'])
        self.assertFalse(exp1_ctx['can_edit'])
        self.assertTrue(exp2_ctx['can_delete'])
        self.assertTrue(exp2_ctx['can_edit'])

        # 4. Check custom category 'Snacks & Drinks' is in available_categories
        self.assertIn('Snacks & Drinks', room_ctx['available_categories'])

        # 5. Check Scenario Breakdowns in context (ABC and AB)
        scenarios = room_ctx['scenario_breakdowns']
        self.assertGreaterEqual(len(scenarios), 2)

        # ABC scenario check: 3 participants, subtotal ₹3000, average ₹1000
        sc_abc = next(s for s in scenarios if s['participant_count'] == 3)
        self.assertEqual(sc_abc['subtotal'], Decimal('3000.00'))
        self.assertEqual(sc_abc['fair_share'], Decimal('1000.00'))

        # AB scenario check: 2 participants, subtotal ₹1000, average ₹500
        sc_ab = next(s for s in scenarios if s['participant_count'] == 2)
        self.assertEqual(sc_ab['subtotal'], Decimal('1000.00'))
        self.assertEqual(sc_ab['fair_share'], Decimal('500.00'))

        # 6. Check UI elements in rendered HTML
        self.assertContains(resp_user2, 'sharing-filters-toolbar')
        self.assertContains(resp_user2, 'id="roomFilterPaidBy"')
        self.assertContains(resp_user2, 'id="roomFilterSplitWith"')
        self.assertContains(resp_user2, 'id="roomFilterCategorySelect"')
        self.assertContains(resp_user2, 'id="addSharedCategoryModal"')
        self.assertContains(resp_user2, 'id="sharedCategoryHistoryModal"')
        self.assertContains(resp_user2, 'id="memberSplitBreakdownModal"')
        self.assertContains(resp_user2, 'openMemberSplitBreakdownModal')

        # 7. User 1 (Manohar) logs in and deletes exp1 successfully
        self.client.login(username='manohar', password='secretpassword')
        auth_del_resp = self.client.post(reverse('delete_shared_expense', args=[exp1.id]), follow=True)
        self.assertEqual(auth_del_resp.status_code, 200)
        self.assertFalse(SharedExpense.objects.filter(id=exp1.id).exists(), "Bill 1 must be deleted by its creator/payer")

    def test_month_year_filter_and_scenario_settle_up(self):
        """
        Tests:
        1. Month & Year filter bar rendered in Room Sharing & Trip Sharing.
        2. Filtering by month/year updates group expenses and context totals.
        3. Settlement calculation: calculates exact 'B pays A ₹...' instructions.
        4. Settle button posts to settle_shared_scenario, marks scenario bills as settled (cleared).
        5. Once settled, balances show ₹0.00 Cleared.
        6. Reopen action reopens balances.
        """
        # 1. Setup Room group
        room_group = SharingGroup.objects.create(
            name="Uppal Room",
            group_type="room",
            total_members=3,
            passkey="ROOM-9029",
            creator=self.user1
        )
        SharingGroupMembership.objects.create(group=room_group, user=self.user1, role="creator")
        SharingGroupMembership.objects.create(group=room_group, user=self.user2, role="member")
        SharingGroupMembership.objects.create(group=room_group, user=self.user3, role="member")

        # Setup Trip group
        trip_group = SharingGroup.objects.create(
            name="Goa Trip 2026",
            group_type="trip",
            total_members=3,
            passkey="TRIP-4444",
            creator=self.user1
        )
        SharingGroupMembership.objects.create(group=trip_group, user=self.user1, role="creator")
        SharingGroupMembership.objects.create(group=trip_group, user=self.user2, role="member")
        SharingGroupMembership.objects.create(group=trip_group, user=self.user3, role="member")

        # 2. Add expenses in Room:
        # November 2026: A pays ₹5000, B pays ₹3000, split between A and B (User 1 and User 2)
        exp_nov_ab1 = SharedExpense.objects.create(
            group=room_group,
            created_by=self.user1,
            paid_by=self.user1,
            date=datetime.date(2026, 11, 5),
            amount=Decimal('5000.00'),
            category='Rent & Housing',
            description='Room Advance'
        )
        exp_nov_ab1.split_members.set([self.user1, self.user2])

        exp_nov_ab2 = SharedExpense.objects.create(
            group=room_group,
            created_by=self.user2,
            paid_by=self.user2,
            date=datetime.date(2026, 11, 10),
            amount=Decimal('3000.00'),
            category='Groceries',
            description='Provisions'
        )
        exp_nov_ab2.split_members.set([self.user1, self.user2])

        # October 2026 expense (should be excluded when November is selected)
        exp_oct = SharedExpense.objects.create(
            group=room_group,
            created_by=self.user1,
            paid_by=self.user1,
            date=datetime.date(2026, 10, 15),
            amount=Decimal('2000.00'),
            category='Food & Dining',
            description='Old October Dinner'
        )
        exp_oct.split_members.set([self.user1, self.user2])

        self.client.login(username='manohar', password='secretpassword')

        # 3. Access Room Sharing with November 2026 filter
        resp_nov = self.client.get(reverse('room_tracker') + '?mode=room&month=11&year=2026')
        self.assertEqual(resp_nov.status_code, 200)

        # Verify Month & Year filter bar is rendered
        self.assertContains(resp_nov, 'id="roomMonthYearForm"')
        self.assertContains(resp_nov, 'Showing: <strong>November 2026</strong>')

        # Verify October expense is excluded from November context
        nov_room_ctx = resp_nov.context['room_group']
        self.assertEqual(nov_room_ctx['expenses_count'], 2)
        nov_exp_ids = [e['id'] for e in nov_room_ctx['expenses_history']]
        self.assertIn(exp_nov_ab1.id, nov_exp_ids)
        self.assertIn(exp_nov_ab2.id, nov_exp_ids)
        self.assertNotIn(exp_oct.id, nov_exp_ids)

        # 4. Check Settlement Instructions for AB scenario in November:
        # A paid 5000, B paid 3000 -> Total 8000 -> Avg 4000 each -> B owes A 1000
        scenarios = nov_room_ctx['scenario_breakdowns']
        sc_ab = next(s for s in scenarios if s['participant_count'] == 2)
        self.assertEqual(sc_ab['subtotal'], Decimal('8000.00'))
        self.assertEqual(sc_ab['fair_share'], Decimal('4000.00'))
        self.assertFalse(sc_ab['is_settled'])
        self.assertTrue(any('pays' in inst and '1,000' in inst for inst in sc_ab['settlement_instructions']))

        # 5. Access Trip Sharing page to verify Trip Month & Year filter
        resp_trip = self.client.get(reverse('room_tracker') + '?mode=trip&month=11&year=2026')
        self.assertEqual(resp_trip.status_code, 200)
        self.assertContains(resp_trip, 'id="tripMonthYearForm"')
        self.assertContains(resp_trip, 'Showing: <strong>November 2026</strong>')

        # 6. User settles the AB scenario via POST
        settle_resp = self.client.post(
            reverse('settle_shared_scenario', args=[room_group.id]),
            {
                'scenario_code': 'AB',
                'participant_ids': json.dumps([self.user1.id, self.user2.id]),
                'action': 'settle',
                'month': '11',
                'year': '2026'
            },
            follow=True
        )
        self.assertEqual(settle_resp.status_code, 200)
        self.assertContains(settle_resp, 'marked as settled and cleared')

        # Verify expenses are now marked is_settled=True in database
        exp_nov_ab1.refresh_from_db()
        exp_nov_ab2.refresh_from_db()
        self.assertTrue(exp_nov_ab1.is_settled)
        self.assertTrue(exp_nov_ab2.is_settled)

        # 7. Check room page after settlement:
        # Scenario AB is now fully settled, net balance for participants is ₹0.00
        resp_after_settle = self.client.get(reverse('room_tracker') + '?mode=room&month=11&year=2026')
        settled_scenarios = resp_after_settle.context['room_group']['scenario_breakdowns']
        sc_ab_settled = next(s for s in settled_scenarios if s['participant_count'] == 2)
        self.assertTrue(sc_ab_settled['is_settled'])
        for p in sc_ab_settled['participants']:
            self.assertEqual(p['balance'], Decimal('0.00'))
            self.assertEqual(p['balance_status'], 'settled')

        # 8. Reopen scenario
        unsettle_resp = self.client.post(
            reverse('settle_shared_scenario', args=[room_group.id]),
            {
                'scenario_code': 'AB',
                'participant_ids': json.dumps([self.user1.id, self.user2.id]),
                'action': 'unsettle',
                'month': '11',
                'year': '2026'
            },
            follow=True
        )
        self.assertEqual(unsettle_resp.status_code, 200)
        exp_nov_ab1.refresh_from_db()
        self.assertFalse(exp_nov_ab1.is_settled)


class ViewerSharingAccessTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.owner = User.objects.create_user(username='manohar', password='password123')
        self.owner_profile = UserProfile.objects.create(user=self.owner, full_name='Manohar Anreddy', is_profile_setup=True)
        self.roommate = User.objects.create_user(username='rakesh', password='password123')
        UserProfile.objects.create(user=self.roommate, full_name='Rakesh', is_profile_setup=True)

        # Create room group for owner
        self.room_group = SharingGroup.objects.create(
            group_type='room',
            name='Uppal Room',
            passkey='ROOM-9999',
            total_members=2,
            creator=self.owner,
            is_active=True
        )
        SharingGroupMembership.objects.create(group=self.room_group, user=self.owner, role='creator')
        SharingGroupMembership.objects.create(group=self.room_group, user=self.roommate, role='member')

        # Add shared expense
        self.bill = SharedExpense.objects.create(
            group=self.room_group,
            paid_by=self.owner,
            date=datetime.date(2026, 11, 1),
            description='DSL Mall Dmart',
            category='Groceries',
            amount=Decimal('3000.00'),
            created_by=self.owner
        )
        self.bill.split_members.set([self.owner, self.roommate])

        # Create viewer user
        self.viewer = User.objects.create_user(username='manohar_viewer', password='viewerpassword123')
        self.viewer_profile = UserProfile.objects.create(
            user=self.viewer,
            full_name='Viewer User',
            is_viewer=True,
            viewer_of=self.owner,
            is_profile_setup=True
        )

    def test_viewer_sees_owner_room_group(self):
        """Viewer profile sees the owner's active room group, member cards, and bills in read-only mode."""
        self.client.login(username='manohar_viewer', password='viewerpassword123')
        response = self.client.get(reverse('room_tracker') + '?mode=room&month=11&year=2026')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['is_viewer'])
        self.assertTrue(response.context['has_room_group'])
        self.assertEqual(response.context['room_group']['name'], 'Uppal Room')
        self.assertEqual(response.context['room_group']['expenses_count'], 1)
        self.assertContains(response, 'Viewer Mode (Read-Only)')
        self.assertContains(response, 'DSL Mall Dmart')

    def test_viewer_cannot_add_or_settle_shared_bills(self):
        """Viewer profile cannot add bills or settle scenarios."""
        self.client.login(username='manohar_viewer', password='viewerpassword123')
        add_resp = self.client.post(reverse('add_shared_expense'), {
            'group_id': self.room_group.id,
            'description': 'Hacked Bill',
            'amount': '100.00',
            'category': 'Other'
        }, follow=True)
        self.assertEqual(add_resp.status_code, 200)
        self.assertFalse(SharedExpense.objects.filter(description='Hacked Bill').exists())

        settle_resp = self.client.post(reverse('settle_shared_scenario', args=[self.room_group.id]), {
            'scenario_code': 'AB',
            'participant_ids': json.dumps([self.owner.id, self.roommate.id]),
            'action': 'settle'
        }, follow=True)
        self.assertEqual(settle_resp.status_code, 200)
        self.bill.refresh_from_db()
        self.assertFalse(self.bill.is_settled)


class PersonalTrackerSharedExpenseInclusionTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='manohar', password='password123')
        UserProfile.objects.create(user=self.user, full_name='Manohar Anreddy', is_profile_setup=True)
        self.roommate = User.objects.create_user(username='rakesh', password='password123')
        UserProfile.objects.create(user=self.roommate, full_name='Rakesh', is_profile_setup=True)

        self.client.login(username='manohar', password='password123')

        # Personal expense of ₹500
        PersonalExpense.objects.create(
            user=self.user,
            date=datetime.date(2026, 11, 5),
            category='Food & Dining',
            description='Dinner out',
            amount=Decimal('500.00')
        )

        # Room sharing group with a ₹3,000 bill split 2 ways (user's share = ₹1,500)
        self.group = SharingGroup.objects.create(
            group_type='room',
            name='Uppal Room',
            passkey='ROOM-1111',
            total_members=2,
            creator=self.user,
            is_active=True
        )
        SharingGroupMembership.objects.create(group=self.group, user=self.user, role='creator')
        SharingGroupMembership.objects.create(group=self.group, user=self.roommate, role='member')

        shared_bill = SharedExpense.objects.create(
            group=self.group,
            paid_by=self.roommate,
            date=datetime.date(2026, 11, 2),
            description='D-Mart Groceries',
            category='Groceries',
            amount=Decimal('3000.00'),
            created_by=self.roommate
        )
        shared_bill.split_members.set([self.user, self.roommate])

    def test_personal_tracker_includes_shared_bill_share(self):
        """Personal tracker includes user's ₹1,500 share in total spend, categories, and past entries."""
        response = self.client.get(reverse('home') + '?month=11&year=2026')
        self.assertEqual(response.status_code, 200)

        # Total month spent: ₹500 (personal) + ₹1,500 (shared share) = ₹2,000
        self.assertEqual(response.context['total_month_spent'], Decimal('2000.00'))

        # Category breakdown contains Groceries (₹1,500) and Food & Dining (₹500)
        cats = {c['name']: c['amount'] for c in response.context['category_breakdown']}
        self.assertEqual(cats.get('Groceries'), Decimal('1500.00'))
        self.assertEqual(cats.get('Food & Dining'), Decimal('500.00'))

        # Past entries contain 2 items
        self.assertEqual(len(response.context['all_expenses']), 2)
        shared_item = next(e for e in response.context['all_expenses'] if getattr(e, 'is_shared', False))
        self.assertEqual(shared_item.amount, Decimal('1500.00'))
        self.assertEqual(shared_item.shared_total_bill, Decimal('3000.00'))

        # Verify badge in HTML response
        self.assertContains(response, 'Uppal Room Share')
        self.assertContains(response, 'of ₹3000.00')


class LendBorrowTrackerTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='manohar', password='password123')
        UserProfile.objects.create(user=self.user, full_name='Manohar Anreddy', is_profile_setup=True)
        self.client.login(username='manohar', password='password123')

    def test_add_loan_given_with_monthly_interest(self):
        """Adding a loan given with monthly interest: ₹10,000 at 10%/mo for 6 months -> ₹6,000 interest, ₹16,000 total."""
        response = self.client.post(reverse('add_loan_record'), {
            'transaction_type': 'given',
            'person_name': 'Rakesh Sharma',
            'phone': '9876543210',
            'amount': '10000.00',
            'given_date': '2026-11-01',
            'expected_return_date': '2027-05-01',
            'has_interest': 'on',
            'interest_rate': '10',
            'interest_period': 'month',
            'duration_value': '6',
            'duration_unit': 'months',
            'notes': 'Friend loan'
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        record = LoanRecord.objects.get(person_name='Rakesh Sharma')
        self.assertEqual(record.amount, Decimal('10000.00'))
        self.assertTrue(record.has_interest)
        self.assertEqual(record.calculated_interest, Decimal('6000.00'))
        self.assertEqual(record.total_expected_amount, Decimal('16000.00'))
        self.assertEqual(record.status, 'pending')

    def test_add_loan_taken_with_yearly_interest(self):
        """Adding a loan taken with annual interest: ₹10,000 at 10%/yr for 6 months -> ₹500 interest, ₹10,500 total."""
        response = self.client.post(reverse('add_loan_record'), {
            'transaction_type': 'taken',
            'person_name': 'Suresh Bank',
            'amount': '10000.00',
            'given_date': '2026-11-01',
            'has_interest': 'on',
            'interest_rate': '10',
            'interest_period': 'year',
            'duration_value': '6',
            'duration_unit': 'months',
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        record = LoanRecord.objects.get(person_name='Suresh Bank')
        self.assertEqual(record.transaction_type, 'taken')
        self.assertEqual(record.calculated_interest, Decimal('500.00'))
        self.assertEqual(record.total_expected_amount, Decimal('10500.00'))

    def test_toggle_loan_settled(self):
        """Toggling settlement marks pending loan as settled, and reopening marks back to pending."""
        record = LoanRecord.objects.create(
            user=self.user,
            transaction_type='given',
            person_name='Sai Teja',
            amount=Decimal('5000.00'),
            given_date=datetime.date(2026, 11, 1),
            status='pending'
        )

        # Toggle to settled
        resp1 = self.client.post(reverse('toggle_loan_settled', args=[record.id]), follow=True)
        self.assertEqual(resp1.status_code, 200)
        record.refresh_from_db()
        self.assertEqual(record.status, 'settled')
        self.assertIsNotNone(record.settled_at)

        # Toggle back to pending
        resp2 = self.client.post(reverse('toggle_loan_settled', args=[record.id]), follow=True)
        self.assertEqual(resp2.status_code, 200)
        record.refresh_from_db()
        self.assertEqual(record.status, 'pending')


class RupeeRouteEnhancementsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='manohar_rr', password='password123')
        self.profile = UserProfile.objects.create(
            user=self.user,
            full_name='Manohar Anreddy',
            age=26,
            is_profile_setup=True
        )
        self.roommate = User.objects.create_user(username='sai_rr', password='password123')
        UserProfile.objects.create(user=self.roommate, full_name='Saiteja', age=25, is_profile_setup=True)

        PersonalExpense.objects.create(
            user=self.user,
            date=datetime.date(2026, 11, 10),
            category='Shopping',
            description='Jacket',
            amount=Decimal('2500.00')
        )

        self.room_group = SharingGroup.objects.create(
            group_type='room',
            name='Metro Room',
            passkey='ROOM-7788',
            total_members=2,
            creator=self.user,
            is_active=True
        )
        SharingGroupMembership.objects.create(group=self.room_group, user=self.user, role='creator')
        SharingGroupMembership.objects.create(group=self.room_group, user=self.roommate, role='member')

        self.trip_group = SharingGroup.objects.create(
            group_type='trip',
            name='Goa Trip',
            passkey='TRIP-7788',
            total_members=2,
            creator=self.user,
            is_active=True
        )
        SharingGroupMembership.objects.create(group=self.trip_group, user=self.user, role='creator')
        SharingGroupMembership.objects.create(group=self.trip_group, user=self.roommate, role='member')

        r_bill = SharedExpense.objects.create(
            group=self.room_group, paid_by=self.user, date=datetime.date(2026, 11, 5),
            description='Rent', category='Rent & Housing', amount=Decimal('10000.00'), created_by=self.user
        )
        r_bill.split_members.set([self.user, self.roommate])

        t_bill = SharedExpense.objects.create(
            group=self.trip_group, paid_by=self.roommate, date=datetime.date(2026, 11, 6),
            description='Hotel', category='Travel & Commute', amount=Decimal('4000.00'), created_by=self.roommate
        )
        t_bill.split_members.set([self.user, self.roommate])

        LoanRecord.objects.create(
            user=self.user, transaction_type='given', person_name='Kiran',
            amount=Decimal('5000.00'), given_date=datetime.date(2026, 11, 1), status='pending'
        )

    def test_login_lands_on_analytics_and_brand_ui(self):
        """Logging in lands directly on RupeeRoute Analytics with pie charts, sidebar link, and theme toggle."""
        resp = self.client.post(reverse('login'), {'username': 'manohar_rr', 'password': 'password123'}, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'expenses/analytics.html')
        self.assertContains(resp, 'RupeeRoute')
        self.assertContains(resp, 'themeToggleBtn')
        self.assertContains(resp, 'Personal Tracking')
        self.assertContains(resp, 'Room Tracking')
        self.assertContains(resp, 'Trip Sharing')
        self.assertContains(resp, 'Money Borrow &amp; Lend')

        # Personal total = 2500 (personal) + 5000 (room share) + 2000 (trip share) = 9500
        self.assertEqual(resp.context['personal_total'], Decimal('9500.00'))
        self.assertEqual(resp.context['room_total'], Decimal('10000.00'))
        self.assertEqual(resp.context['trip_total'], Decimal('4000.00'))
        self.assertEqual(resp.context['total_given_expected'], Decimal('5000.00'))

    def test_pdf_exports_across_all_modules(self):
        """All PDF export endpoints return valid downloadable PDF bytes."""
        self.client.login(username='manohar_rr', password='password123')
        urls = [
            reverse('export_personal_pdf') + '?month=11&year=2026',
            reverse('export_personal_pdf') + '?month=11&year=2026&category=Shopping',
            reverse('export_sharing_pdf') + '?mode=room&month=11&year=2026',
            reverse('export_sharing_pdf') + '?mode=trip&month=11&year=2026&category=Travel+%26+Commute',
            reverse('export_lend_borrow_pdf') + '?tab=given',
        ]
        for u in urls:
            resp = self.client.get(u)
            self.assertEqual(resp.status_code, 200, f"Failed for {u}")
            self.assertEqual(resp['Content-Type'], 'application/pdf')
            self.assertTrue(resp.content.startswith(b'%PDF-'), f"Invalid PDF bytes for {u}")

    def test_custom_member_count_and_shared_future_month_split(self):
        """Supports custom member counts (>10) and splitting room/trip bills across future months."""
        self.client.login(username='manohar_rr', password='password123')
        # Add room bill split across 3 future months
        resp = self.client.post(reverse('add_shared_expense'), {
            'group_id': self.room_group.id,
            'date': '2026-11-15',
            'description': 'Quarterly WiFi',
            'category': 'Utilities & Bills',
            'amount': '3000.00',
            'paid_by': self.user.id,
            'split_members': [self.user.id, self.roommate.id],
            'is_split': 'true',
            'split_months': '3',
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        q_bills = list(SharedExpense.objects.filter(description__startswith='Quarterly WiFi').order_by('date'))
        self.assertEqual(len(q_bills), 3)
        self.assertEqual([b.date for b in q_bills], [
            datetime.date(2026, 11, 15),
            datetime.date(2026, 12, 15),
            datetime.date(2027, 1, 15),
        ])
        self.assertEqual(sum(b.amount for b in q_bills), Decimal('3000.00'))

        # Create group with custom member count 14 (new temp user)
        u3 = User.objects.create_user(username='custom_creator', password='password123')
        UserProfile.objects.create(user=u3, full_name='Creator', is_profile_setup=True)
        self.client.login(username='custom_creator', password='password123')
        create_resp = self.client.post(reverse('create_sharing_group'), {
            'group_type': 'trip',
            'total_members': '14',
            'name': 'College Reunion',
        }, follow=True)
        self.assertEqual(create_resp.status_code, 200)
        grp = SharingGroup.objects.get(name='College Reunion')
        self.assertEqual(grp.total_members, 14)

    def test_remove_profile_picture(self):
        """Remove Picture action clears existing avatar on profile update."""
        import tempfile
        from django.test import override_settings
        from django.core.files.uploadedfile import SimpleUploadedFile
        with tempfile.TemporaryDirectory() as tmp_media:
            with override_settings(MEDIA_ROOT=tmp_media):
                self.profile.avatar = SimpleUploadedFile("test_avatar.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", content_type="image/png")
                self.profile.save()
                self.assertTrue(bool(self.profile.avatar))

                self.client.login(username='manohar_rr', password='password123')
                resp = self.client.post(reverse('update_profile'), {'remove_avatar': '1'}, follow=True)
                self.assertEqual(resp.status_code, 200)
                self.profile.refresh_from_db()
                self.assertFalse(bool(self.profile.avatar))


class NotificationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user_a = User.objects.create_user(username='roommate_a', password='password123')
        self.user_b = User.objects.create_user(username='roommate_b', password='password123')
        self.user_c = User.objects.create_user(username='roommate_c', password='password123')
        for u, name in [(self.user_a, 'Alice'), (self.user_b, 'Bob'), (self.user_c, 'Charlie')]:
            UserProfile.objects.create(user=u, full_name=name, is_profile_setup=True)

        self.group = SharingGroup.objects.create(
            group_type='room',
            name='Trio Flat',
            passkey='ROOM-3333',
            total_members=3,
            creator=self.user_a,
            is_active=True
        )
        SharingGroupMembership.objects.create(group=self.group, user=self.user_a, role='creator')
        SharingGroupMembership.objects.create(group=self.group, user=self.user_b, role='member')
        SharingGroupMembership.objects.create(group=self.group, user=self.user_c, role='member')

    def test_roommate_changes_create_unread_notifications_and_redirect(self):
        """
        While A is offline, B adds, edits, settles, and deletes bills.
        When A logs in, A sees the red unread badge, all notifications, and clicking redirects directly.
        """
        # B logs in and adds a bill
        self.client.login(username='roommate_b', password='password123')
        self.client.post(reverse('add_shared_expense'), {
            'group_id': self.group.id,
            'date': '2026-11-10',
            'description': 'Dmart Groceries',
            'category': 'Groceries',
            'amount': '1500.00',
            'paid_by': self.user_b.id,
            'split_members': [self.user_a.id, self.user_b.id],
        })
        bill = SharedExpense.objects.get(description='Dmart Groceries')

        # B edits the bill
        self.client.post(reverse('edit_shared_expense', args=[bill.id]), {
            'date': '2026-11-10',
            'description': 'Dmart Groceries',
            'category': 'Groceries',
            'amount': '1800.00',
            'paid_by': self.user_b.id,
            'split_members': [self.user_a.id, self.user_b.id],
        })

        # B settles AB scenario
        self.client.post(reverse('settle_shared_scenario', args=[self.group.id]), {
            'scenario_code': 'AB',
            'participant_ids': json.dumps([self.user_a.id, self.user_b.id]),
            'action': 'settle',
            'month': '11',
            'year': '2026',
        })

        # B adds and deletes a quick tea bill
        self.client.post(reverse('add_shared_expense'), {
            'group_id': self.group.id,
            'date': '2026-11-11',
            'description': 'Morning Tea',
            'category': 'Food',
            'amount': '30.00',
            'paid_by': self.user_b.id,
            'split_members': [self.user_a.id, self.user_b.id],
        })
        tea_bill = SharedExpense.objects.get(description='Morning Tea')
        self.client.post(reverse('delete_shared_expense', args=[tea_bill.id]))

        # Bob himself should NOT receive self-notifications
        self.assertEqual(Notification.objects.filter(recipient=self.user_b).count(), 0)
        # Alice & Charlie each received 5 unread notifications (add, edit, settle, add tea, delete tea)
        self.assertEqual(Notification.objects.filter(recipient=self.user_a, is_read=False).count(), 5)
        self.assertEqual(Notification.objects.filter(recipient=self.user_c, is_read=False).count(), 5)

        # Now Alice logs in
        self.client.logout()
        self.client.login(username='roommate_a', password='password123')
        analytics_resp = self.client.get(reverse('analytics'))
        self.assertEqual(analytics_resp.status_code, 200)
        self.assertEqual(analytics_resp.context['unread_notifications_count'], 5)
        self.assertContains(analytics_resp, 'notifUnreadDot')
        self.assertContains(analytics_resp, 'Dmart Groceries')
        self.assertContains(analytics_resp, 'settled subgroup AB')
        self.assertContains(analytics_resp, 'Morning Tea')

        # Clicking notification marks it read and redirects to exact target URL
        edit_notif = Notification.objects.filter(recipient=self.user_a, action_type='edited').first()
        click_resp = self.client.get(reverse('notification_click', args=[edit_notif.id]))
        self.assertEqual(click_resp.status_code, 302)
        self.assertIn(f'#room-exp-{bill.id}', click_resp.url)
        edit_notif.refresh_from_db()
        self.assertTrue(edit_notif.is_read)
        self.assertEqual(Notification.objects.filter(recipient=self.user_a, is_read=False).count(), 4)

        # Clicking Mark all read clears remaining unread count
        mark_resp = self.client.post(reverse('notifications_mark_all_read'), follow=True)
        self.assertEqual(mark_resp.status_code, 200)
        self.assertEqual(Notification.objects.filter(recipient=self.user_a, is_read=False).count(), 0)
        self.assertNotContains(mark_resp, 'id="notifUnreadDot"')


