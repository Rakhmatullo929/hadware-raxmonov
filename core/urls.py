from django.urls import path

from . import views

urlpatterns = [
    path('', views.root, name='root'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('rentals/', views.rentals, name='rentals'),
    path('reports/', views.reports, name='reports'),

    path('products/', views.ProductListView.as_view(), name='product_list'),
    path('products/new/', views.ProductCreateView.as_view(), name='product_create'),
    path('products/<int:pk>/edit/', views.ProductUpdateView.as_view(), name='product_update'),
    path(
        'products/<int:pk>/toggle/',
        views.ProductToggleActiveView.as_view(),
        name='product_toggle_active',
    ),
    path('categories/new/', views.CategoryCreateView.as_view(), name='category_create'),

    path('customers/', views.CustomerListView.as_view(), name='customer_list'),
    path('customers/new/', views.CustomerCreateView.as_view(), name='customer_create'),
    path('customers/<int:pk>/', views.CustomerDetailView.as_view(), name='customer_detail'),
    path('customers/<int:pk>/edit/', views.CustomerUpdateView.as_view(), name='customer_update'),
]
