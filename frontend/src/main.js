// PROTOTYPE：仅用于独立分支的词汇布局评审，不合并进产品。
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router'
import './style.css'
import App from './App.vue'

function mountApp() {
  const app = createApp(App)
  app.use(createPinia())
  app.use(router)
  app.mount('#app')
}

if (import.meta.env.DEV && import.meta.env.VITE_VOCAB_PROTOTYPE === '1') {
  Promise.all([import('./api/client'), import('./api/vocabularyPrototypeFixture')])
    .then(([{ default: client }, { installVocabularyPrototypeFixture }]) => {
      installVocabularyPrototypeFixture(client)
      mountApp()
    })
} else {
  mountApp()
}
