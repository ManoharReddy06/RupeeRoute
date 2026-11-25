import datetime
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from expenses.models import UserProfile, PersonalExpense


class Command(BaseCommand):
    help = 'Seeds initial users: admin (fresh setup) & manohar (active tracker with sample expenses)'

    def handle(self, *args, **options):
        # 1. Fresh user to test the first-time Profile Setup flow
        admin_user, _ = User.objects.get_or_create(
            username='admin',
            defaults={'email': 'admin@example.com', 'is_staff': True, 'is_superuser': True}
        )
        admin_user.set_password('admin123')
        admin_user.save()

        admin_profile, _ = UserProfile.objects.get_or_create(user=admin_user)
        admin_profile.is_profile_setup = False
        admin_profile.save()

        # 2. Demo user with pre-configured profile and personal expenses
        demo_user, _ = User.objects.get_or_create(
            username='manohar',
            defaults={'email': 'manohar@example.com'}
        )
        demo_user.set_password('demo123')
        demo_user.save()

        demo_profile, _ = UserProfile.objects.get_or_create(user=demo_user)
        demo_profile.full_name = 'Manohar Anreddy'
        demo_profile.age = 25
        demo_profile.is_profile_setup = True
        demo_profile.save()

        # Seed sample expenses for demo_user in current month (November 2026)
        sample_expenses = [
            (datetime.date(2026, 11, 10), 'Curd', 'Food/Curd', Decimal('50.00')),
            (datetime.date(2026, 11, 12), 'Rapido to Office', 'Travel', Decimal('120.00')),
            (datetime.date(2026, 11, 1), 'Room Rent November', 'Rent', Decimal('7500.00')),
            (datetime.date(2026, 11, 5), 'Jio Recharge', 'Recharge', Decimal('499.00')),
            (datetime.date(2026, 11, 15), 'Dmart Supermarket', 'Food', Decimal('1350.00')),
            (datetime.date(2026, 11, 18), 'Zudio Clothes', 'Shopping', Decimal('1800.00')),
        ]

        # Clear existing expenses for demo_user to avoid duplicates
        PersonalExpense.objects.filter(user=demo_user).delete()

        for d, desc, cat, amt in sample_expenses:
            PersonalExpense.objects.create(
                user=demo_user,
                date=d,
                description=desc,
                category=cat,
                amount=amt
            )

        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS("Database seeded successfully!"))
        self.stdout.write(self.style.SUCCESS("1. Fresh Profile Setup Test: admin / admin123"))
        self.stdout.write(self.style.SUCCESS("2. Active Personal Tracker Demo: manohar / demo123"))
        self.stdout.write(self.style.SUCCESS("=" * 60))

