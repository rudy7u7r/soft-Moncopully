from django.contrib import admin
from .models import (
    Usuario, Raza, Madre, Bovino, PajuelaSemen, Parentesco,
    AlertaConsanguinidad, Inseminacion, DiagnosticoGestacion, Parto
)

admin.site.register(Usuario)
admin.site.register(Raza)
admin.site.register(Madre)
admin.site.register(Bovino)
admin.site.register(PajuelaSemen)
admin.site.register(Parentesco)
admin.site.register(AlertaConsanguinidad)
admin.site.register(Inseminacion)
admin.site.register(DiagnosticoGestacion)
admin.site.register(Parto)
