export const api = { async fetchReplicas(id){ return fetch('/api/v1/projects/'+id+'/replicas').then(r=>r.json()); } };
