import assert from 'node:assert/strict';
import { injectExperimentHtml, rootState, summarizeExperiment } from './experiment_worker.js';

const liveMarkup = `<!doctype html><html><head></head><body><div class="tabs" id="tabs"><button class="tab on" data-p="overview">Dirección</button><button class="tab" data-p="commercial">Comercial</button><button class="tab" data-p="state">Estado vivo</button></div><section class="page on" id="overview"></section></body></html>`;
const injected = injectExperimentHtml(liveMarkup);
assert.match(injected, /data-p="experiments">Experimentos<\/button>/);
assert.match(injected, /id="experiments"/);
assert.match(injected, /Experiment Engine v1/);
assert.match(injected, /Aprender qué vende mejor/);
assert.match(injected, /id="lumenExperimentScript"/);

const payload = {
  meta: { root_keys: 2 },
  module_data: {
    experiment_engine: {
      version: '1.0-zero-experiment-engine',
      status: 'active',
      policy: '80_20_exploit_explore',
      exploit_share: 0.8,
      explore_share: 0.2,
      decision_sequence: 6,
      exploit_decisions: 5,
      explore_decisions: 1,
      winner_product: null,
      winner_channel: null,
      verified_settlements: 0,
      verified_revenue_usd: 0,
      bottleneck: 'demand_discovery',
      next_decision: 'Explotar V1 y medir.',
      current_experiment: {
        id: 'EXP-TEST-1',
        mode: 'exploit',
        campaign_id: 'ACQ-BUYER',
        variant_id: 'ACQ-BUYER-V1',
        audience: 'buyer',
        angle: 'ahorro_tiempo',
        baseline_clicks: 3,
        baseline_leads: 1,
        baseline_verified_companies: 0,
        baseline_conversion_rate: 1 / 3,
        dispatch: { channel: 'email_b2b', reason: 'governed_canary_scheduled' },
      },
      history: [{
        id: 'EXP-TEST-1', mode: 'exploit', campaign_id: 'ACQ-BUYER', variant_id: 'ACQ-BUYER-V1',
        angle: 'ahorro_tiempo', baseline_clicks: 3, baseline_leads: 1, baseline_verified_companies: 0,
        baseline_conversion_rate: 1 / 3,
      }],
      guardrails: {
        monetary_budget_usd: 0,
        paid_media_authority_changed: false,
        binding_authority_changed: false,
        search_budget_increased: false,
        hard_bottleneck_override: false,
      },
    },
    cognitive_director_learning: {
      top_product: { product_slug: 'export-pulse', samples: 12, settlement_rate: 0.25, realized_revenue_usd: 75 },
      top_channel: { source: 'instagram', campaign: 'organic-export', samples: 10 },
    },
    autonomous_director: { bottleneck: 'demand_discovery' },
  },
};

const state = rootState(payload);
assert.equal(state, payload.module_data);
const summary = summarizeExperiment(state);
assert.equal(summary.status, 'active');
assert.equal(summary.policy, '80_20_exploit_explore');
assert.equal(summary.exploit_share, 0.8);
assert.equal(summary.explore_share, 0.2);
assert.equal(summary.experiment_id, 'EXP-TEST-1');
assert.equal(summary.mode, 'exploit');
assert.equal(summary.campaign_id, 'ACQ-BUYER');
assert.equal(summary.variant_id, 'ACQ-BUYER-V1');
assert.equal(summary.sample_clicks, 3);
assert.equal(summary.sample_leads, 1);
assert.equal(summary.product_winner, 'export-pulse');
assert.equal(summary.channel_winner, 'instagram');
assert.equal(summary.guardrails.monetary_budget_usd, 0);
assert.equal(summary.guardrails.paid_media_authority_changed, false);
assert.equal(summary.guardrails.binding_authority_changed, false);
assert.equal(summary.guardrails.search_budget_increased, false);
assert.equal(summary.guardrails.hard_bottleneck_override, false);

console.log('EXPERIMENT_DASHBOARD_WORKER ok');
