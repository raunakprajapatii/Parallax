import type { ChatClient, ChatResponse } from './api'

const demoResponse: ChatResponse = {
  conversationId: 'demo-atlas-conversation',
  answer: 'The Atlas launch has two active risks. Jira ticket ATL-42 is blocked by API rate limits, so the team should confirm a limit increase or agree on a fallback. [1] The design handoff is also delayed; follow up with the design owner and request a firm delivery time. [2] ATL-51 is already in review, so keep it moving while the blockers are cleared. [3] The launch brief and owner list provide the project context for coordinating these next steps. [4]',
  citations: [
    { number: 1, recordId: 'jira:ATL-42', title: 'ATL-42 · API rate limit blocks launch flow', source: 'jira' },
    { number: 2, recordId: 'gmail:design-handoff', title: 'Design handoff timing and remaining assets', source: 'gmail' },
    { number: 3, recordId: 'jira:ATL-51', title: 'ATL-51 · Launch review checklist', source: 'jira' },
    { number: 4, recordId: 'notion:atlas-launch-brief', title: 'Atlas Launch · Brief and owners', source: 'notion' },
  ], traceId: 'run_demo_atlas_01', memoryUsed: [],
}

export const mockChat: ChatClient = async () => {
  await new Promise((resolve) => window.setTimeout(resolve, 1100))
  return demoResponse
}
