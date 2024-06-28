from django.contrib import admin
from django.urls import path, include
from predictor import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('predictor.urls')),
    path('malaria-risk-map/', views.malaria_risk_map, name='malaria_risk_map'),
]
