# -*- coding:utf-8 -*-
"""
Author:
    Yuef Zhang
Reference:
    [1] Zhou G, Zhu X, Song C, et al. Deep interest network for click-through rate prediction[C]//Proceedings of the 24th ACM SIGKDD International Conference on Knowledge Discovery & Data Mining. ACM, 2018: 1059-1068. (https://arxiv.org/pdf/1706.06978.pdf)
"""
import torch
import torch.nn as nn
import torch.nn.functional as F

from .basemodel import BaseModel
from ..inputs import get_varlen_pooling_list, embedding_lookup, get_dense_input, varlen_embedding_lookup, SparseFeat, DenseFeat, VarLenSparseFeat, combined_dnn_input
from ..layers import FM, DNN
from ..layers.sequence import AttentionSequencePoolingLayer


class DIN(BaseModel):
    """Instantiates the Deep Interest Network architecture.

    :param dnn_feature_columns: An iterable containing all the features used by deep part of the model.
    :param history_feature_list: list,to indicate  sequence sparse field
    :param dnn_use_bn: bool. Whether use BatchNormalization before activation or not in deep net
    :param dnn_hidden_units: list,list of positive integer or empty list, the layer number and units in each layer of deep net
    :param dnn_activation: Activation function to use in deep net
    :param att_hidden_size: list,list of positive integer , the layer number and units in each layer of attention net
    :param att_activation: Activation function to use in attention net
    :param att_weight_normalization: bool.Whether normalize the attention score of local activation unit.
    :param l2_reg_dnn: float. L2 regularizer strength applied to DNN
    :param l2_reg_embedding: float. L2 regularizer strength applied to embedding vector
    :param dnn_dropout: float in [0,1), the probability we will drop out a given DNN coordinate.
    :param init_std: float,to use as the initialize std of embedding vector
    :param seed: integer ,to use as random seed.
    :param task: str, ``"binary"`` for  binary logloss or  ``"regression"`` for regression loss
    :return:  A PyTorch model instance.

    """
    def __init__(self,
                 dnn_feature_columns, 
                 history_feature_list,
                 dnn_use_bn=False,
                 embedding_size=8,
                 dnn_hidden_units=(256, 128),
                 dnn_activation='relu',
                 att_hidden_size=[80,40],
                 att_activation='Dice',
                 l2_reg_dnn=0.0,
                 init_std=0.0001,
                 dnn_dropout=0,
                 task='binary', device='cpu'):

        super(DIN, self).__init__([], dnn_feature_columns, embedding_size=embedding_size,
                                dnn_hidden_units=dnn_hidden_units, l2_reg_linear=0,
                                l2_reg_dnn=l2_reg_dnn, init_std=init_std,
                                dnn_dropout=dnn_dropout, dnn_activation=dnn_activation,
                                task=task, device=device)
       
        sparse_feature_columns = list(filter(lambda x:isinstance(x,SparseFeat),dnn_feature_columns)) if dnn_feature_columns else []
        varlen_sparse_feature_columns = list(filter(lambda x: isinstance(x, VarLenSparseFeat), dnn_feature_columns)) if dnn_feature_columns else []

        history_feature_columns = []
        sparse_varlen_feature_columns = []
        history_fc_names = list(map(lambda x: "hist_" + x, history_feature_list))
        for fc in varlen_sparse_feature_columns:
            feature_name = fc.name
            if feature_name in history_fc_names:
                history_feature_columns.append(fc)
            else:
                sparse_varlen_feature_columns.append(fc)

        history_feature_columns = []
        sparse_varlen_feature_columns = []
        history_fc_names = list(map(lambda x: "hist_" + x, history_feature_list))

        query_emb_list = embedding_lookup(self.embedding_dict, self.feature_index, sparse_feature_columns, 
                                          history_feature_list, history_feature_list, to_list=True)
        keys_emb_list = embedding_lookup(self.embedding_dict, self.feature_index, history_feature_columns,
                                         history_fc_names, history_fc_names, to_list=True)
        dnn_input_emb_list = embedding_lookup(self.embedding_dict, self.feature_index, sparse_feature_columns,
                                              mask_feat_list=history_feature_list, to_list=True)

        sequence_embed_dict = varlen_embedding_lookup(self.embedding_dict, self.feature_index, sparse_varlen_feature_columns)
        sequence_embed_list = get_varlen_pooling_list(sequence_embed_dict, self.feature_index, sparse_varlen_feature_columns,to_list=True)
        
        dnn_input_emb_list += sequence_embed_list

        # concatenate
        self.query_emb = torch.cat(query_emb_list, dim=-1)          # [B, 1, E]
        self.keys_emb = torch.cat(keys_emb_list, dim=-1)            # [B, T, E]
        self.keys_length = torch.ones((self.query_emb.size(0), 1))      # [B, 1]
        self.deep_input_emb = torch.cat(dnn_input_emb_list, dim=-1)


        self.atten = AttentionSequencePoolingLayer(att_hidden_units=att_hidden_size,
                                                   embedding_dim=embedding_size,
                                                   activation=att_activation)
        
        self.dnn = DNN(inputs_dim=self.compute_input_dim(dnn_feature_columns, embedding_size),
                       hidden_units=dnn_hidden_units,
                       activation=dnn_activation,
                       dropout_rate=dnn_dropout,
                       l2_reg=l2_reg_dnn)
        self.dnn_linear = nn.Linear(dnn_hidden_units[-1], 1, bias=False).to(device)
        self.to(device)

    def forward(self, X):
        sparse_embedding_list, dense_value_list = self.input_from_feature_columns(X, self.dnn_feature_columns,
                                                                                  self.embedding_dict)

        hist = self.atten(self.query_emb, self.keys_emb, self.keys_length)

        deep_input_emb = torch.cat((self.deep_input_emb, hist), dim=-1)
        deep_input_emb = deep_input_emb.view(deep_input_emb.size(0), -1)

        dnn_input = combined_dnn_input([deep_input_emb], dense_value_list)
        dnn_output = self.dnn(dnn_input)
        dnn_logit = self.dnn_linear(dnn_output)

        y_pred = self.out(dnn_logit)

        return y_pred


if __name__ == '__main__':
    pass

