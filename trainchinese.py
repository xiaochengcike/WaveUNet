from __future__ import print_function

import os
import time

import numpy as np
import soundfile as sf
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils import data
from torchvision import transforms

from readchinese import Dataset, Testset,Valtset
#from unet import Unet
from modelStruct.unet import Unet
from tensorboardX import SummaryWriter
from transformData import mu_law_encode,mu_law_decode
# In[2]:

batchSize = 2
sampleSize = 16384*batchSize  # the length of the sample size
sample_rate = 16384
songnum=45
savemusic='vsCorpus/nus1xtr{}.wav'
#savemusic0='vsCorpus/nus10xtr{}.wav'
#savemusic1='vsCorpus/nus11xtr{}.wav'
resumefile = 'model/instrument1song'  # name of checkpoint
continueTrain = False  # whether use checkpoint
sampleCnt=0
USEBOARD = False
quan=False
if(USEBOARD):writer = SummaryWriter()

os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
os.environ["CUDA_VISIBLE_DEVICES"] = "0"  # use specific GPU

# In[4]:
from datetime import datetime
current_time = datetime.now().strftime('%b%d_%H-%M-%S')
if(USEBOARD):writer = SummaryWriter(log_dir='runs/'+str(current_time)+'mulaw,chinesewav,15filtersize',comment="uwavenet")


use_cuda = torch.cuda.is_available()  # whether have available GPU
torch.manual_seed(1)
device = torch.device("cuda" if use_cuda else "cpu")
# device = 'cpu'
# torch.set_default_tensor_type('torch.cuda.FloatTensor') #set_default_tensor_type as cuda tensor


#training_set = Dataset(np.arange(45), 'ccmixter3/',pad=pad,transform=transform)
#validation_set = Testset(np.arange(45,50), 'ccmixter3/',pad=pad)
#training_set = Dataset(np.arange(45), 'chinesesongs/')
#test_set = Testset(np.arange(0,50), 'chinesesongs/')
#validation_set =Valtset(np.arange(45,50), 'chinesesongs/')
training_set = Dataset(np.arange(1), 'chinesesongs/')
test_set = Testset(np.arange(1), 'chinesesongs/')
validation_set =Valtset(np.arange(1), 'chinesesongs/')


worker_init_fn = lambda worker_id: np.random.seed(np.random.get_state()[1][0] + worker_id)
loadtr = data.DataLoader(training_set, batch_size=45,shuffle=True,num_workers=10,worker_init_fn=worker_init_fn)
loadtest = data.DataLoader(test_set,batch_size=1,num_workers=10)
loadval = data.DataLoader(validation_set,batch_size=5,num_workers=10,worker_init_fn=worker_init_fn)
# In[6]:

#model = Unet(skipDim, quantization_channels, residualDim,device)
model = Unet()
#model = nn.DataParallel(model)
model = model.cuda()
criterion = nn.MSELoss()
# in wavenet paper, they said crossentropyloss is far better than MSELoss
optimizer = optim.Adam(model.parameters(), lr=1e-4, weight_decay=1e-6,betas=(0.9, 0.999))
# use adam to train
#print(model)
#print(model.parameters())
maxloss=np.zeros(50)+100

iteration = 0
start_epoch=0
if continueTrain:  # if continueTrain, the program will find the checkpoints
    if os.path.isfile(resumefile):
        print("=> loading checkpoint '{}'".format(resumefile))
        checkpoint = torch.load(resumefile)
        start_epoch = checkpoint['epoch']
        iteration = checkpoint['iteration']
        model.load_state_dict(checkpoint['state_dict'])
        optimizer.load_state_dict(checkpoint['optimizer'])
        print("=> loaded checkpoint '{}' (epoch {})"
              .format(resumefile, checkpoint['epoch']))
    else:
        print("=> no checkpoint found at '{}'".format(resumefile))


# In[9]:


def test(epoch):  # testing data
    model.eval()
    start_time = time.time()
    with torch.no_grad():
        for iloader, xtrain, ytrain in loadtest:
            iloader=iloader.item()
            listofpred0 = []
            cnt,aveloss=0,0
            for ind in range(0, xtrain.shape[-1] - sampleSize, sampleSize):
                #output = model(xtrain[:, :, ind:ind + sampleSize].to(device), torch.randint(0, 1, (24,)))
                output = model(xtrain[:, :,ind:ind + sampleSize].to(device))
                listofpred0.append(output.reshape(-1))
                loss = criterion(output, (ytrain[:, :,ind:ind + sampleSize].to(device)))
                cnt+=1
                aveloss += float(loss)
            aveloss /= cnt
            print('loss for test:{},num{},epoch{}'.format(aveloss, iloader,epoch))
            ans0 = mu_law_decode(np.concatenate(listofpred0))
            if not os.path.exists('vsCorpus/'): os.makedirs('vsCorpus/')
            sf.write(savemusic.format(iloader), ans0, sample_rate)
            print('test stored done', np.round(time.time() - start_time))

def val(epoch):
    model.eval()
    start_time = time.time()
    cnt, aveloss = 0, 0
    with torch.no_grad():
        for iloader, xtrain, ytrain in loadval:
            for ind in range(0, xtrain.shape[-1], sampleSize // batchSize):
                if (xtrain[0, 0, ind:ind + sampleSize].shape[0] < (sampleSize)): break
                output = model(xtrain[:, :, ind:ind + sampleSize].to(device))
                loss = criterion(output, (ytrain[:, :, ind:ind + sampleSize].to(device)))
                cnt += 1
                aveloss += float(loss)
        aveloss /= cnt
        print('loss for validation:{:.5f},epoch{},valtime{}'.format(aveloss, epoch,np.round(time.time() - start_time)))
        if (USEBOARD): writer.add_scalar('waveunet val loss', aveloss, iteration)

def train(epoch):  # training data, the audio except for last 15 seconds
    for iloader,xtrain, ytrain in loadtr:
        startx = 0
        idx = np.arange(startx, xtrain.shape[-1], 2000)
        #np.random.shuffle(idx)
        cnt, aveloss = 0, 0
        start_time = time.time()
        model.train()
        for i, ind in enumerate(idx):
            if (xtrain[0, 0, ind:ind + sampleSize].shape[0] < (sampleSize)): break
            data = xtrain[:, :, ind:ind + sampleSize].to(device)
            target = ytrain[:, :,ind:ind + sampleSize].to(device)
            optimizer.zero_grad()
            #output = model(data,torch.randint(0, 1, (24,)))
            output = model(data)
            #print(model.decoder0[0].weight[0])
            loss = criterion(output, target)
            aveloss+=float(loss)
            cnt+=1
            loss.backward()
            optimizer.step()
            global sampleCnt
            sampleCnt+=1
            if sampleCnt % 10000 == 0 and sampleCnt > 0:
                for param in optimizer.param_groups:
                    param['lr'] *= 0.98
                    #if(param['lr'] < 1e-5):param['lr'] = 1e-5
        global iteration
        iteration += 1
        print('loss for train:{:.6f},epoch{},({:.3f} sec/step)'.format(
            aveloss / cnt, epoch,time.time() - start_time))

        if (USEBOARD): writer.add_scalar('waveunet loss', (aveloss / cnt), iteration)

    if epoch % 5 == 0:
        if not os.path.exists('model/'): os.makedirs('model/')
        state = {'epoch': epoch,
                 'state_dict': model.state_dict(),
                 'optimizer': optimizer.state_dict(),
                 'iteration': iteration}
        torch.save(state, resumefile)
        print('write finish')


# In[ ]:

print('training...')
for epoch in range(100000):
    train(epoch+start_epoch)
    val(epoch+start_epoch)
    #test(epoch + start_epoch)
    if (epoch+start_epoch) % 100 == 0 and epoch+start_epoch > 0: test(epoch+start_epoch)