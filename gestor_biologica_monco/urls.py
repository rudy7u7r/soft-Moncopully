from django.urls import path
from . import views

# Asegúrate de tener app_name si lo usas, si no, omítelo
app_name = 'gestor_biologica_monco'

urlpatterns = [
    # Agrega esta línea para manejar la ruta principal (cuando entras a 127.0.0.1:8000)
    path('', views.inicio, name='raiz'), 
    
    # Tus otras rutas que ya tenías
    path('inicio/', views.inicio, name='inicio'),
    path('historial/', views.historial, name='historial'),
    path('linaje/', views.linaje, name='linaje'),
    path('arbol_genealogico/', views.linaje, name='arbol_genealogico'),
    path('verificar/', views.verificar, name='verificar'),
    path('login/', views.login, name='login'),
    path('esperando-permisos/', views.esperando_permisos, name='esperando_permisos'),
    path('usuarios/', views.gestion_usuarios, name='gestion_usuarios'),
    path('inseminacion/', views.inseminacion, name='inseminacion'),
    path('inseminacion/nueva/', views.nueva_inseminacion, name='nueva_inseminacion'),
    path('inseminacion/diagnostico/', views.registro_prenez, name='registro_prenez'),
    path('pajuelas/', views.pajuelas, name='pajuelas'),
    path('pajuelas/nueva/', views.nueva_pajuela, name='nueva_pajuela'),
    path('rendimiento/', views.rendimiento_genetico, name='rendimiento'),
    path('informes/', views.informes, name='informes'),
    path('exportar/inseminaciones/', views.exportar_inseminaciones, name='exportar_inseminaciones'),
    path('exportar/alertas/', views.exportar_alertas, name='exportar_alertas'),
    path('exportar/inventario/', views.exportar_inventario, name='exportar_inventario'),
    path('exportar/terreno/', views.exportar_ganado_terreno, name='exportar_ganado_terreno'),
    path('exportar/plantilla-rfid/', views.descargar_plantilla_rfid, name='descargar_plantilla_rfid'),
    path('bovino/nuevo/', views.nuevo_bovino, name='nuevo_bovino'),
]