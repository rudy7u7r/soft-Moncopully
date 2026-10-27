from django.urls import path

from . import views

app_name = "gestor_biologica_monco"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("historial/", views.historial, name="historial"),
    path("linaje/", views.linaje, name="linaje"),
    path("verificar/", views.verificar, name="verificar"),
    path("login/", views.login, name="login"),
]
