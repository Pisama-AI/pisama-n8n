'use client'

import { Suspense } from 'react'
import { signIn } from 'next-auth/react'
import { useSearchParams } from 'next/navigation'
import { PisamaMark } from '@/components/common/PisamaMark'

function SignInInner() {
  const params = useSearchParams()
  const callbackUrl = params.get('callbackUrl') || '/onboarding'

  return (
    <main className="min-h-screen bg-paper text-ink flex items-center justify-center px-6">
      <div className="w-full max-w-sm rounded-lg border border-rule bg-paper-2 p-8 text-center">
        <div className="flex justify-center mb-4">
          <PisamaMark size={32} color="var(--ink)" />
        </div>
        <h1 className="font-serif text-2xl mb-2">
          pisama <span className="text-ink-3">for n8n</span>
        </h1>
        <p className="text-sm text-ink-3 mb-8">
          Sign in to connect your n8n and start catching failures.
        </p>
        <button
          onClick={() => signIn('google', { callbackUrl })}
          className="w-full px-5 py-2.5 rounded-lg bg-evidence text-evidence-ink font-semibold hover:bg-evidence-2 transition-colors"
        >
          Continue with Google
        </button>
        <p className="mt-6 text-xs text-ink-4">
          Prefer to keep everything on your own machine?{' '}
          <a
            href="https://github.com/Pisama-AI/pisama-n8n"
            className="text-evidence hover:underline"
          >
            Self-host it
          </a>
          .
        </p>
      </div>
    </main>
  )
}

export default function SignIn() {
  return (
    <Suspense>
      <SignInInner />
    </Suspense>
  )
}
