# core/expenses.py
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.utils.decorators import method_decorator
from core.permissions import require_permission
from core.models import Expense
from core.forms import ExpenseForm


# Money screens are guarded: only roles with the 'accounts' area may open them.
@method_decorator(require_permission('accounts'), name='dispatch')
class ExpenseListView(LoginRequiredMixin, ListView):
    model = Expense
    template_name = 'expenses/expense_list.html'
    context_object_name = 'expenses'
    paginate_by = 25
    ordering = ['-date', '-id']

    def get_queryset(self):
        qs = super().get_queryset().select_related('supplier', 'staff', 'bank_account', 'created_by')
        # Simple filters (optional query params)
        category = self.request.GET.get('category')
        src = self.request.GET.get('source')  # cash/bank
        q = self.request.GET.get('q')

        if category:
            qs = qs.filter(category=category)
        if src in ['cash', 'bank']:
            qs = qs.filter(payment_source=src)
        if q:
            qs = qs.filter(
                Q(description__icontains=q) |
                Q(reference__icontains=q) |
                Q(supplier__name__icontains=q) |
                Q(staff__full_name__icontains=q)
            )
        return qs

class ExpenseCreateView(LoginRequiredMixin, CreateView):
    model = Expense
    form_class = ExpenseForm
    template_name = 'expenses/expense_form.html'
    success_url = reverse_lazy('expense_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

class ExpenseUpdateView(LoginRequiredMixin, UpdateView):
    model = Expense
    form_class = ExpenseForm
    template_name = 'expenses/expense_form.html'
    success_url = reverse_lazy('expense_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

class ExpenseDeleteView(LoginRequiredMixin, DeleteView):
    model = Expense
    template_name = 'expenses/expense_confirm_delete.html'
    success_url = reverse_lazy('expense_list')
