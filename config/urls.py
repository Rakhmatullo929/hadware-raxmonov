from django.urls import path

from . import views

urlpatterns = [
    path('', views.root, name='root'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('reports/', views.reports, name='reports'),
    path('reports/revenue/', views.report_revenue, name='report_revenue'),
    path('reports/top-products/', views.report_top_products, name='report_top_products'),
    path('reports/debtors/', views.report_debtors, name='report_debtors'),
    path('reports/debtors.csv', views.report_debtors_csv, name='report_debtors_csv'),
    path('reports/stock/', views.report_stock, name='report_stock'),

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
    path('rentals/<int:pk>/contract/', views.rental_contract, name='rental_contract'),
    path(
        'rentals/<int:pk>/contract.pdf',
        views.rental_contract_pdf,
        name='rental_contract_pdf',
    ),
    path('rentals/<int:pk>/close/', views.RentalCloseView.as_view(), name='rental_close'),

    path('rentals/<int:pk>/edit/', views.RentalEditView.as_view(), name='rental_edit'),
    path(
        'rentals/<int:pk>/payment/add/',
        views.RentalPaymentAddView.as_view(), name='rental_payment_add',
    ),
    path(
        'rentals/<int:pk>/payment/<int:payment_pk>/edit/',
        views.RentalPaymentEditView.as_view(), name='rental_payment_edit',
    ),
    path(
        'rentals/<int:pk>/payment/<int:payment_pk>/delete/',
        views.RentalPaymentDeleteView.as_view(), name='rental_payment_delete',
    ),
    path(
        'rentals/<int:pk>/item/add/',
        views.RentalItemAddView.as_view(), name='rental_item_add',
    ),
    path(
        'rentals/<int:pk>/item/<int:item_pk>/edit/',
        views.RentalItemEditView.as_view(), name='rental_item_edit',
    ),
    path(
        'rentals/<int:pk>/item/<int:item_pk>/remove/',
        views.RentalItemRemoveView.as_view(), name='rental_item_remove',
    ),
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
