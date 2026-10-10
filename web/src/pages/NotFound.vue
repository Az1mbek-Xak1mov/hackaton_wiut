<script setup lang="ts">
import { t } from '@/i18n'
</script>

<template>
  <div class="page">
    <div class="page-head"><div><h1>{{ t('Page not found') }}</h1><p class="meta">{{ t('This address does not exist in Converza.') }}</p></div></div>
    <div class="row"><RouterLink class="btn btn-primary" to="/analyse">{{ t('Analyse a document') }}</RouterLink><RouterLink class="btn" to="/bank">{{ t('Bank officer view') }}</RouterLink></div>
  </div>
</template>
