import datetime
from django import forms
from django.contrib.auth.models import User
from .models import UserProfile, PersonalExpense


class LoginForm(forms.Form):
    username = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'Enter your username',
            'autocomplete': 'username',
            'autofocus': True,
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'placeholder': 'Enter your password',
            'autocomplete': 'current-password',
        })
    )


class RegisterForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'Choose a username',
            'autofocus': True,
        })
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'form-input',
            'placeholder': 'you@example.com (optional)',
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'placeholder': 'Create a password',
        })
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'placeholder': 'Confirm your password',
        })
    )

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("This username is already taken. Please choose another.")
        return username

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')

        if password and confirm_password and password != confirm_password:
            self.add_error('confirm_password', "Passwords do not match.")

        return cleaned_data


class ProfileSetupForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['full_name', 'age', 'avatar']
        widgets = {
            'full_name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Enter your full name',
                'required': True,
                'autofocus': True
            }),
            'age': forms.NumberInput(attrs={
                'class': 'form-input',
                'placeholder': 'Enter your age',
                'min': '1',
                'max': '120',
                'required': True
            }),
            'avatar': forms.FileInput(attrs={
                'class': 'form-input',
                'accept': 'image/*'
            }),
        }


class PersonalExpenseForm(forms.ModelForm):
    CATEGORY_CHOICES = [
        ('Food', 'Food'),
        ('Travel', 'Travel'),
        ('Rent', 'Rent'),
        ('Shopping', 'Shopping'),
        ('Recharge', 'Recharge'),
        ('Entertainment', 'Entertainment'),
        ('Other', 'Other'),
    ]

    category = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'list': 'category-options',
            'placeholder': 'e.g. Food, Travel, Rent, Shopping, Recharge, Food/Curd'
        })
    )

    class Meta:
        model = PersonalExpense
        fields = ['date', 'description', 'category', 'amount']
        widgets = {
            'date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-input',
            }),
            'description': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g. Curd, Rapido, Grocery, Room Rent',
                'required': True,
            }),
            'amount': forms.NumberInput(attrs={
                'class': 'form-input',
                'step': '0.01',
                'min': '0.01',
                'placeholder': '0.00',
                'required': True,
            }),
        }


class CreateViewerForm(forms.Form):
    full_name = forms.CharField(
        max_length=120,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'e.g. Dad, Brother, Friend, Roommate (Optional)',
        })
    )
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'Choose username or email for viewer',
            'autofocus': True,
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'placeholder': 'Create password for viewer',
        })
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'placeholder': 'Confirm password',
        })
    )

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("This username is already taken. Please choose another username.")
        return username

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')

        if password and confirm_password and password != confirm_password:
            self.add_error('confirm_password', "Passwords do not match.")

        return cleaned_data
