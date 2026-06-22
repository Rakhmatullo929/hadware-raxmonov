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
    path('reports/returns/', views.report_returns, name='report_returns'),
    path('reports/returns.csv', views.report_returns_csv, name='report_returns_csv'),
    path(
        'reports/payment-methods/',
        views.report_payment_methods,
        name='report_payment_methods',
    ),

    path('products/', views.ProductListView.as_view(), name='product_list'),
    path('products/new/', views.ProductCreateView.as_view(), name='product_create'),
    path('products/<int:pk>/edit/', views.ProductUpdateView.as_view(), name='product_update'),
    path(
        'products/<int:pk>/toggle/',
        views.ProductToggleActiveView.as_view(),
        name='product_toggle_active',
    ),
    path('categories/new/', views.CategoryCreateView.as_view(), name='category_create'),

    # Подозрения: позиции, превышающие норму проката товара
    path('suspicions/', views.product_suspicions, name='product_suspicions'),

    # Посещаемость рабочих
    path('attendance/', views.attendance_journal, name='attendance_journal'),
    path(
        'attendance/<int:worker_id>/toggle/',
        views.attendance_toggle,
        name='attendance_toggle',
    ),
    path('workers/', views.WorkerListView.as_view(), name='worker_list'),
    path('workers/new/', views.WorkerCreateView.as_view(), name='worker_create'),
    path(
        'workers/<int:pk>/edit/',
        views.WorkerUpdateView.as_view(),
        name='worker_update',
    ),
    path(
        'workers/<int:pk>/toggle/',
        views.WorkerToggleActiveView.as_view(),
        name='worker_toggle_active',
    ),

    # Зарплата сотрудников
    path('salary/', views.salary_index, name='salary_index'),
    path(
        'salary/<int:worker_id>/base/',
        views.salary_base_update, name='salary_base_update',
    ),
    path(
        'salary/<int:worker_id>/entries/',
        views.salary_entries_modal, name='salary_entries_modal',
    ),
    path(
        'salary/<int:worker_id>/entries/add/',
        views.salary_entry_create, name='salary_entry_create',
    ),
    path(
        'salary/entries/<int:entry_id>/delete/',
        views.salary_entry_delete, name='salary_entry_delete',
    ),
    path(
        'salary/<int:worker_id>/detail/',
        views.salary_worker_detail, name='salary_worker_detail',
    ),

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
    path(
        'rentals/<int:pk>/return-receipt.pdf',
        views.rental_return_receipt_pdf,
        name='rental_return_receipt_pdf',
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
        'rentals/_/customer-create/',
        views.CustomerCreateInlineView.as_view(),
        name='rental_customer_create',
    ),
    path(
        'rentals/_/product-info/',
        views.ProductInfoView.as_view(),
        name='rental_product_info',
    ),
    path(
        'rentals/_/product-search/',
        views.ItemProductSearchView.as_view(),
        name='rental_item_product_search',
    ),
    path(
        'rentals/_/product-pick/<int:pk>/',
        views.ItemProductPickView.as_view(),
        name='rental_item_product_pick',
    ),
    path(
        'rentals/_/product-clear/',
        views.ItemProductClearView.as_view(),
        name='rental_item_product_clear',
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
