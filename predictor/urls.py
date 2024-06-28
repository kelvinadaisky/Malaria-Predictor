from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('show_top10_map/', views.show_top10_map, name='show_top10_map'),
    path('show_all_map/', views.show_all_map, name='show_all_map'),
]
