import api from './api';

export const userAPI = {
  getFinancialSummary: async () => {
    try {
      const response = await api.get('/user/financial-summary');
      return response.data;
    } catch (error) {
      console.error('Failed to fetch financial summary:', error);
      // Fallback with empty state
      return {
        totalInvested: 0,
        totalAssets: 0,
        netWorth: 0,
        banks: [],
        investments: [],
        isEmpty: true,
      };
    }
  },
  getUploadedDocs: async () => {
    try {
      const response = await api.get('/documents/list');
      return response.data;
    } catch (error) {
      console.error('Failed to fetch uploaded documents:', error);
      return [];
    }
  },
};
