"""Shared RGB feature preprocessing, with explicit legacy grayscale compatibility."""
def build_features(base,grayscale=False):
 import torch
 class Features(torch.nn.Module):
  def __init__(self):
   super().__init__();self.features=base.features;self.pool=base.avgpool;self.prehead=torch.nn.Sequential(*list(base.classifier.children())[:2])
   self.register_buffer('mean',torch.tensor([.485,.456,.406]).reshape(1,3,1,1));self.register_buffer('std',torch.tensor([.229,.224,.225]).reshape(1,3,1,1))
   if grayscale:self.register_buffer('gray',torch.tensor([.299,.587,.114]).reshape(1,3,1,1))
  def forward(self,image):
   pixels=(image*self.gray).sum(dim=1,keepdim=True).repeat(1,3,1,1) if hasattr(self,'gray') else image
   return self.prehead(torch.flatten(self.pool(self.features((pixels-self.mean)/self.std)),1))
 return Features()
