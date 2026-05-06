from django.urls import path

from . import views

urlpatterns = [
    path('', views.root, name='root'),
    path('dashboard/', views.dashboard, name='dashboard'),
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

    path('rentals/', views.RentalListView.as_view(), name='rental_list'),
    path('rentals/new/', views.RentalCreateView.as_view(), name='rental_create'),
    path('rentals/<int:pk>/', views.RentalDetailView.as_view(), name='rental_detail'),
    path('rentals/<int:pk>/return/', views.RentalReturnView.as_view(), name='rental_return'),
    path('rentals/<int:pk>/close/', views.RentalCloseView.as_view(), name='rental_close'),
    path(
        'rentals/_/modal-close/',
        views.RentalModalCloseView.as_view(),
        name='rental_modal_close',
    ),

    path(
        'rentals/_/customer-search/',
        views.CustomerSearchView.as_view(),
        name='rental_customer_search',
    ),
    path(
        'rentals/_/customer-pick/<int:pk>/',
        views.CustomerPickView.as_view(),
        name='rental_customer_pick',
    ),
    path(
        'rentals/_/customer-clear/',
        views.CustomerClearView.as_view(),
        name='rental_customer_clear',
    ),
    path(
        'rentals/_/product-info/',
        views.ProductInfoView.as_view(),
        name='rental_product_info',
    ),
    path(
        'rentals/_/item-row/',
        views.ItemRowNewView.as_view(),
        name='rental_item_row_new',
    ),
    path(
        'rentals/_/item-row-remove/',
        views.ItemRowRemoveView.as_view(),
        name='rental_item_row_remove',
    ),
]
