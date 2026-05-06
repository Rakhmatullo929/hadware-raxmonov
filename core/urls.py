from django.urls import path

from . import views

urlpatterns = [
    path('', views.root, name='root'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('rentals/', views.rentals, name='rentals'),
    path('clients/', views.clients, name='clients'),
    path('products/', views.products, name='products'),
    path('reports/', views.reports, name='reports'),
]
