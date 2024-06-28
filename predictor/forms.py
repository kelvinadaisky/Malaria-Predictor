from django import forms

class CountryForm(forms.Form):
    country = forms.CharField(label='Enter Country', max_length=100)
