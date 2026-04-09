from django.contrib import admin
from .models import Conversation, LongTermMemory

@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('client_id', 'updated_at')
    search_fields = ('client_id',)

@admin.register(LongTermMemory)
class LongTermMemoryAdmin(admin.ModelAdmin):
    list_display = ('client_id', 'created_at')
    search_fields = ('client_id',)
    list_filter = ('created_at',)
