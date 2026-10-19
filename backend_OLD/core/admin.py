from django.contrib import admin
from .models import ConversationHistory, ConversationSummary

@admin.register(ConversationHistory)
class ConversationHistoryAdmin(admin.ModelAdmin):
    list_display = ('client_id', 'role', 'created_at')
    search_fields = ('client_id', 'content')

@admin.register(ConversationSummary)
class ConversationSummaryAdmin(admin.ModelAdmin):
    list_display = ('client_id', 'created_at')
    search_fields = ('client_id', 'summary_text')
