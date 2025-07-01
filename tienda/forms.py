
from django import forms
from .models import ClienteB2C

class RegistroClienteForm(forms.ModelForm):
    contrasena = forms.CharField(widget=forms.PasswordInput)

    class Meta:
        model = ClienteB2C
        fields = ['nombre', 'apellido', 'rut', 'telefono', 'correo', 'contrasena']


class LoginClienteForm(forms.Form):
    correo = forms.EmailField()
    contrasena = forms.CharField(widget=forms.PasswordInput)
