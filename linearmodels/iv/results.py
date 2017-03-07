import datetime as dt

import scipy.stats as stats
from linearmodels.utility import (InvalidTestStatistic, WaldTestStatistic,
                                  _annihilate, _proj, cached_property)
from numpy import c_, diag, log, ones, sqrt, empty
from numpy.linalg import inv, pinv
from pandas import DataFrame, Series


class OLSResults(object):
    def __init__(self, results, model):
        self._resid = results['eps']
        self._params = results['params']
        self._cov = results['cov']
        self.model = model
        self._r2 = results['r2']
        self._cov_type = results['cov_type']
        self._rss = results['residual_ss']
        self._tss = results['total_ss']
        self._s2 = results['s2']
        self._debiased = results['debiased']
        self._f_statistic = results['fstat']
        self._vars = results['vars']
        self._cov_config = results['cov_config']
        self._method = results['method']
        self._kappa = results.get('kappa', None)
        self._datetime = dt.datetime.now()

    def __str__(self):
        return self.summary

    def __repr__(self):
        return self.__str__().as_text() + '\nid: {0}'.format(hex(id(self)))

    def _repr_html_(self):
        return self.summary.as_html() + '<br/>id: {0}'.format(hex(id(self)))

    @property
    def cov_config(self):
        """Parameter values from covariance estimator"""
        return self._cov_config

    @property
    def cov_estimator(self):
        """Type of covariance estimator used to compute covariance"""
        return self._cov_type

    @property
    def cov(self):
        """Estimated covariance of parameters"""
        return self._cov

    @property
    def params(self):
        """Estimated parameters"""
        return self._params

    @property
    def resids(self):
        """Estimated residuals"""
        return self._resid

    @property
    def nobs(self):
        """Number of observations"""
        return self.model.endog.shape[0]

    @property
    def df_resid(self):
        """Residual degree of freedom"""
        return self.nobs - self.model.exog.shape[1]

    @property
    def df_model(self):
        """Model degree of freedom"""
        return self.model._x.shape[1]

    @property
    def has_constant(self):
        """Flag indicating the model includes a constant or equivalent"""
        return self.model.has_constant

    @property
    def kappa(self):
        """k-class estimator value"""
        return self._kappa

    @property
    def rsquared(self):
        """Coefficient of determination (R**2)"""
        return self._r2

    @property
    def rsquared_adj(self):
        """Sample-size adjusted coefficient of determination (R**2)"""
        n, k, c = self.nobs, self.df_model, int(self.has_constant)
        return 1 - ((n - c) / (n - k)) * (1 - self._r2)

    @property
    def cov_type(self):
        """Covariance estimator used"""
        return self._cov_type

    @property
    def std_errors(self):
        """Estimated parameter standard errors"""
        std_errors = sqrt(diag(self.cov))
        return Series(std_errors, index=self._vars, name='stderr')

    @property
    def tstats(self):
        """Parameter t-statistics"""
        return self.params / self.std_errors

    @cached_property
    def pvalues(self):
        """
        Parameter p-vals. Uses t(df_resid) if debiased is True, other normal.
        """
        if self.debiased:
            pvals = 2 - 2 * stats.t.cdf(abs(self.tstats), self.df_resid)
        else:
            pvals = 2 - 2 * stats.norm.cdf(abs(self.tstats))

        return Series(pvals, index=self._vars, name='pvalue')

    @property
    def total_ss(self):
        """Total sum of squares"""
        return self._tss

    @property
    def model_ss(self):
        """Residual sum of squares"""
        return self._tss - self._rss

    @property
    def resid_ss(self):
        """Residual sum of squares"""
        return self._rss

    @property
    def s2(self):
        """Residual variance estimator"""
        return self._s2

    @property
    def debiased(self):
        """Flag indicating whether covariance uses a small-sample adjustment"""
        return self._debiased

    @property
    def f_statistic(self):
        """Joint test of significance for non-constant regressors"""
        return self._f_statistic

    @property
    def method(self):
        """Method used to estimate model parameters"""
        return self._method

    def conf_int(self, level=0.95):
        """
        Confidence interval construction

        Parameters
        ----------
        level : float
            Confidence level for interval

        Returns
        -------
        ci : DataFrame
            Confidence interval of the form [lower, upper] for each parameters
        """
        q = stats.norm.ppf([(1 - level) / 2, 1 - (1 - level) / 2])
        q = q[None, :]
        ci = self.params[:, None] + self.std_errors[:, None] * q
        return DataFrame(ci, index=self._vars, columns=['lower', 'upper'])

    @property
    def f_stat(self):
        """
        Model F-statistic
        
        Returns
        -------
        f : WaldTestStatistic
            Test statistic for null all coefficients excluding constant terms 
            are zero.
        
        Notes
        -----
        Despite name, always implemented using a quadratic-form test based on 
        estimated parameter covariance. Default is to use a chi2 distribution 
        to compute p-values. If ``debiased`` is True, uses an F-distribution.
        """
        p = self.params.values[:, None]
        c = self.cov.values
        if self.has_constant:
            loc = self.model._const_loc
            ex = [i for i in range(len(p)) if i != loc]
            p = p[ex]
            c = c[ex][:, ex]
        stat = p.T @ inv(c) @ p
        df = p.shape[0]
        if self.cov_config['debiased']:
            df_denom = self.nobs - p.shape[0]
            return WaldTestStatistic(stat, 'All coefficients ex. const are 0',
                                     df, df_denom, name='Model F-statistic')
        return WaldTestStatistic(stat, 'All coefficients ex. const are 0',
                                 df, name='Model F-statistic')

    @property
    def summary(self):
        """Summary table of model estimation results"""
        def float4(v):
            out = '{0:5.5g}'.format(v)
            if len(out) < 6 and '.' in out:
                out += '0' * (6 - len(out))
            return out

        def pval_format(v):
            return '{0:4.4f}'.format(v)

        from statsmodels.iolib.summary import Summary, fmt_2cols, \
            SimpleTable, fmt_params
        title = self._method + ' Estimation Summary'
        mod = self.model
        top_left = [('Dep. Variable:', mod.dependent.cols[0]),
                    ('No. Observations:', self.nobs),
                    ('Date:', self._datetime.strftime('%a, %b %d %Y')),
                    ('Time:', self._datetime.strftime('%H:%M:%S')),
                    ('', ''),
                    ('', '')]

        top_right = [('R-squared:', float4(self.rsquared)),
                     ('Adj. R-squared:', float4(self.rsquared_adj)),
                     ('F-statistic:', float4(self.f_statistic.stat)),
                     ('F-stat dist:', str(self.f_statistic.dist_name)),
                     ('F-stat p-value:', pval_format(self.f_statistic.pval)),
                     ('', '')]

        stubs = []
        vals = []
        for stub, val in top_left:
            stubs.append(stub)
            vals.append([val])
        table = SimpleTable(vals, txt_fmt=fmt_2cols, title=title, stubs=stubs)

        # create summary table instance
        smry = Summary()
        # Top Table
        # Parameter table
        fmt = fmt_2cols
        fmt['data_fmts'][1] = '%18s'

        top_right = [('%-21s' % ('  ' + k), v) for k, v in top_right]
        stubs = []
        vals = []
        for stub, val in top_right:
            stubs.append(stub)
            vals.append([val])
        table.extend_right(SimpleTable(vals, stubs=stubs))
        smry.tables.append(table)

        param_data = c_[self.params.values[:, None],
                        self.std_errors.values[:, None],
                        self.tstats.values[:, None],
                        self.pvalues.values[:, None],
                        self.conf_int()]
        data = []
        for row in param_data:
            txt_row = []
            for i, v in enumerate(row):
                f = float4
                if i == 3:
                    f = pval_format
                txt_row.append(f(v))
            data.append(txt_row)
        for row in data:
            row[4] = '[' + row[4]
            row[5] += ']'
        title = 'Parameter Estimates'
        table_stubs = list(self.params.index)
        header = ['Parameters', 'Std. Err.', 'T-stat', 'P-value', 'Lower CI', 'Upper CI']
        table = SimpleTable(data,
                            stubs=table_stubs,
                            txt_fmt=fmt_params,
                            headers=header,
                            title=title)
        smry.tables.append(table)

        instruments = self.model.instruments
        extra_text = []
        if instruments.shape[1] > 0:
            endog = self.model.endog
            extra_text.append('Instrumented: ' + ', '.join(endog.cols))
            extra_text.append('Instruments: ' + ', '.join(instruments.cols))
        extra_text.append('Covariance estimator: {0}'.format(self.cov_type))
        smry.add_extra_txt(extra_text)

        return smry


class _CommonIVResults(OLSResults):
    """
    Results from IV estimation

    Notes
    -----
    .. todo::

        * Hypothesis testing
    """

    def __init__(self, results, model):
        super(_CommonIVResults, self).__init__(results, model)
        self._liml_kappa = results.get('liml_kappa', None)

    @property
    def first_stage(self):
        """
        First stage regression results

        Returns
        -------
        first : FirstStageResults
            Object containing results for diagnosing instrument relevance issues.
        """
        return FirstStageResults(self.model.dependent, self.model.exog,
                                 self.model.endog, self.model.instruments,
                                 self._cov_type, self._cov_config)


class IVResults(_CommonIVResults):
    """
    Results from IV estimation

    Notes
    -----
    .. todo::

        * Hypothesis testing
    """

    def __init__(self, results, model):
        super(IVResults, self).__init__(results, model)
        self._kappa = results.get('kappa', 1)

    @cached_property
    def sargan(self):
        """
        Sargan test of overidentifying restrictions
        
        Returns
        -------
        t : WaldTestStatistic
            Object containing test statistic, pvalue, distribution and null
        
        Notes
        -----
        Requires more instruments than endogenous variables
        
        Tests the ratio of re-projected IV regression residual variance to 
        variance of the IV residuals.
        
        .. math ::
        
          n (1- \epsilon'M_{z}\epsilon/\epsilon'\epsilon) \sim \chi^2_{v}
        
        where :math:`M_{z}` is the annihilator matrix where z is the set of 
        instruments and :math:`\hat{\epsilon}` are the residuals from the IV 
        estimator.  The degree of freedom is the difference between the number
        of instruments and the number of endogenous regressors.

        .. math :: 
        
          v = n_{instr} - n_{exog} 
        """
        z = self.model.instruments.ndarray
        nobs, ninstr = z.shape
        nendog = self.model.endog.shape[1]
        name = 'Sargan\'s test of overidentification'
        if ninstr - nendog == 0:
            return InvalidTestStatistic('Test requires more instruments than '
                                        'endogenous variables.', name=name)

        eps = self.resids.values[:, None]
        u = _annihilate(eps, self.model._z)
        stat = nobs * (1 - (u.T @ u) / (eps.T @ eps)).squeeze()
        null = 'The model is not overidentified.'

        return WaldTestStatistic(stat, null, ninstr - nendog, name=name)

    @cached_property
    def basmann(self):
        """
        Basmann's test of overidentifying restrictions
        
        Returns
        -------
        t : WaldTestStatistic
            Object containing test statistic, pvalue, distribution and null
        
        Notes
        -----
        Requires more instruments than endogenous variables
        
        Tests is a small-sample version of Sargan's test that has the same 
        distribution.
        
        .. math ::
        
          s (n - n_{instr}) / (n - s) \sim \chi^2_{v} 
        
        where :math:`n_{instr}` is the number of instruments, :math:`n_{exog}`
        is the number of exogenous regressors and :math:`n_{endog}` is the 
        number of endogenous regressors.  The degree of freedom is the 
        difference between the number of instruments and the number of 
        endogenous regressors.
        
        .. math :: 
        
          v = n_{instr} - n_{exog} 
        """
        mod = self.model
        ninstr = mod.instruments.shape[1]
        nobs, nendog = mod.endog.shape
        nz = mod._z.shape[1]
        name = 'Basmann\'s test of overidentification'
        if ninstr - nendog == 0:
            return InvalidTestStatistic('Test requires more instruments than '
                                        'endogenous variables.', name=name)
        sargan_test = self.sargan
        s = sargan_test.stat
        stat = s * (nobs - nz) / (nobs - s)
        return WaldTestStatistic(stat, sargan_test.null, sargan_test.df, name=name)

    def _endogeneity_setup(self, vars=None):
        """Setup function for some endogeneity tests"""
        if vars is not None and not isinstance(vars, list):
            vars = [vars]
        nobs = self.model.dependent.shape[0]
        e2 = self.resids.values
        nendog, nexog = self.model.endog.shape[1], self.model.exog.shape[1]
        if vars is None:
            assumed_exog = self.model.endog.ndarray
            aug_exog = c_[self.model.exog.ndarray, assumed_exog]
            still_endog = empty((nobs, 0))
        else:
            assumed_exog = self.model.endog.pandas[vars].values
            ex = [c for c in self.model.endog.cols if c not in vars]
            still_endog = self.model.endog.pandas[ex].values
            aug_exog = c_[self.model.exog.ndarray, assumed_exog]
            null = 'Variables {0} are exogenous'.format(', '.join(vars))
        ntested = assumed_exog.shape[1]

        from linearmodels.iv import IV2SLS
        mod = IV2SLS(self.model.dependent, aug_exog, still_endog,
                     self.model.instruments)
        e0 = mod.fit().resids.values[:, None]

        z2 = c_[self.model.exog.ndarray, self.model.instruments.ndarray]
        z1 = c_[z2, assumed_exog]

        e1 = _proj(e0, z1)
        e2 = _proj(e2, self.model.instruments.ndarray)
        return e0, e1, e2, nobs, nexog, nendog, ntested

    def durbin(self, vars=None):
        r"""
        Durbin's test of exogeneity
        
        Parameters
        ----------
        vars : list(str), optional
            List of variables to test for exogeneity.  If None, all variables 
            are jointly tested. 

        Returns
        -------
        t : WaldTestStatistic
            Object containing test statistic, pvalue, distribution and null
        
        Notes
        -----
        
        Test statistic is difference between sum of squared OLS and sum of 
        squared IV residuals where each set of residuals has been projected 
        onto the set of instruments in teh IV model.  
        
        .. math ::
        
          TODO 

        """
        null = 'All endogenous variables are exogenous'
        if vars is not None:
            null = 'Variables {0} are exogenous'.format(', '.join(vars))

        e0, e1, e2, nobs, nexog, nendog, ntested = self._endogeneity_setup(vars)
        stat = e1.T @ e1 - e2.T @ e2
        stat /= (e0.T @ e0) / nobs

        name = 'Durbin test of exogeneity'
        df = ntested
        return WaldTestStatistic(stat.squeeze(), null, df, name=name)

    def wu_hausman(self, vars=None):
        r"""
        Wu-Hausman test of exogeneity

        Parameters
        ----------
        vars : list(str), optional
            List of variables to test for exogeneity.  If None, all variables 
            are jointly tested. 

        Returns
        -------
        t : WaldTestStatistic
            Object containing test statistic, pvalue, distribution and null
        
        Notes
        -----
        
        Test statistic is based on the difference between ...
        
        .. math ::
        
          TODO 

        """
        null = 'All endogenous variables are exogenous'
        if vars is not None:
            null = 'Variables {0} are exogenous'.format(', '.join(vars))

        e0, e1, e2, nobs, nexog, nendog, ntested = self._endogeneity_setup(vars)

        df = ntested
        df_denom = nobs - nexog - nendog - ntested
        delta = (e1.T @ e1 - e2.T @ e2)
        stat = delta / df
        stat /= (e0.T @ e0 - delta) / df_denom
        stat = stat.squeeze()

        name = 'Wu-Hausman test of exogeneity'
        return WaldTestStatistic(stat, null, df, df_denom, name=name)

    @cached_property
    def wooldridge_score(self):
        r"""
        Wooldridge's score test of exogeneity
         
        Returns
        -------
        t : WaldTestStatistic
            Object containing test statistic, pvalue, distribution and null

        Notes
        -----
        Wooldridge's test examines whether there is correlation between the
        errors produced when the endogenous variable are treated as 
        exogenous so that the model can be fit by OLS, and the component of 
        the endogenous variables that cannot be explained by the instruments.
        
        The test is implemented using a regression,
         
        .. math ::
        
          1 = \gamma_1 \hat{\epsilon}_1 \hat{v}_{1,i} + \ldots 
            + \gamma_p \hat{\epsilon}_1 \hat{v}_{p,i} + \eta_i
        
        where :math:`\hat{v}_{j,i}` is the residual from regressing endogenous
        variable :math:`x_j` on the exogenous variables and instruments.
        
        The test is a :math:`n\times R^2 \sim \chi^2_{p}`.
        """
        from linearmodels.iv.model import _OLS

        e = _annihilate(self.model.dependent.ndarray, self.model._x)
        r = _annihilate(self.model.endog.ndarray, self.model._z)
        nobs = e.shape[0]
        res = _OLS(ones((nobs, 1)), r * e).fit('unadjusted')
        stat = res.nobs - res.resid_ss
        df = self.model.endog.shape[1]
        null = 'Endogenous variables are exogenous'
        name = 'Wooldridge\'s score test of exogeneity'
        return WaldTestStatistic(stat, null, df, name=name)

    @cached_property
    def wooldridge_regression(self):
        r"""
        Wooldridge's regression test of exogeneity 

        Returns
        -------
        t : WaldTestStatistic
            Object containing test statistic, pvalue, distribution and null

        Notes
        -----
        Wooldridge's test examines whether there is correlation between the
        components of the endogenous variables that cannot be explained by
        the instruments and the OLS regression residuals.
         
        The test is implemented as an OLS where 

        .. math ::

          y_i = x_{1i}\beta_i + x_{2i}\beta_2 + \hat{e}_i\gamma + \epsilon_i
        
        where :math:`x_{1i}` are the exogenous regressors, :math:`x_{2i}` are 
        the  endogenous regressors and :math:`\hat{e}_{i}` are the residuals 
        from regressing the endogenous variables on the exogenous variables 
        and instruments. The null is :math:`\gamma=0` and is implemented
        using a Wald test.  The covariance estimator used in the test is
        identical to the covariance estimator used with ``fit``. 
        """
        from linearmodels.iv.model import _OLS
        r = _annihilate(self.model.endog.ndarray, self.model._z)
        augx = c_[self.model._x, r]
        mod = _OLS(self.model.dependent, augx)
        res = mod.fit(self.cov_type, **self.cov_config)
        norig = self.model._x.shape[1]
        test_params = res.params.values[norig:]
        test_cov = res.cov.values[norig:, norig:]
        stat = test_params.T @ inv(test_cov) @ test_params
        df = len(test_params)
        null = 'Endogenous variables are exogenous'
        name = 'Wooldridge\'s regression test of exogeneity'
        return WaldTestStatistic(stat, null, df, name=name)

    @cached_property
    def wooldridge_overid(self):
        r"""
        Wooldridge's score test of overidentification 

        Returns
        -------
        t : WaldTestStatistic
            Object containing test statistic, pvalue, distribution and null

        Notes
        -----
        Wooldridge's test examines whether there is correlation between the
        model residuals and the component of the instruments that is 
        orthogonal to the endogenous variables. Define :math:`\tilde{z}`
        to be the residuals of the instruments regressed on the exogenous
        variables and the first-stage fitted values of the endogenous 
        variables.  The test is computed as a regression
        
        .. math ::
        
          1 = \gamma_1 \hat{\epsilon}_i \tilde{z}_{i,1} + \ldots + 
              \gamma_q \hat{\epsilon}_i \tilde{z}_{i,q}
        
        where :math:`q = n_{instr} - n_{endog}`.  The test is a 
        :math:`n\times R^2 \sim \chi^2_{q}`.
        
        The order of the instruments does not affect this test.
        """
        from linearmodels.iv.model import _OLS
        exog, endog = self.model.exog, self.model.endog
        instruments = self.model.instruments
        nobs, nendog = endog.shape
        ninstr = instruments.shape[1]
        if ninstr - nendog == 0:
            import warnings
            warnings.warn('Test requires more instruments than '
                          'endogenous variables',
                          UserWarning)
            return WaldTestStatistic(0, 'Test is not feasible.', 1, name='Infeasible test.')

        endog_hat = _proj(endog.ndarray, c_[exog.ndarray, instruments.ndarray])
        q = instruments.ndarray[:, :(ninstr - nendog)]
        q_res = _annihilate(q, c_[self.model.exog.ndarray, endog_hat])
        test_functions = q_res * self.resids.values[:, None]
        res = _OLS(ones((nobs, 1)), test_functions).fit('unadjusted')

        stat = res.nobs * res.rsquared
        df = ninstr - nendog
        null = 'Model is not overidentified.'
        name = 'Wooldridge\'s score test of overidentification'
        return WaldTestStatistic(stat, null, df, name=name)

    @cached_property
    def anderson_rubin(self):
        """
        Anderson-Rubin test of overidentifying restrictions
        
        Returns
        -------
        t : WaldTestStatistic
            Object containing test statistic, pvalue, distribution and null

        Notes
        -----
        The Anderson-Rubin test examines whether the value of :math:`\kappa`
        computed for the LIML estimator is sufficiently close to one to 
        indicate the model is not overidentified. The test statistic is
        
        .. math ::
        
          n \ln(\hat{\kappa}) \sim \chi^2_{q}
        
        where :math:`q = n_{instr} - n_{endog}`.
        """
        nobs, ninstr = self.model.instruments.shape
        nendog = self.model.endog.shape[1]
        name = 'Anderson-Rubin test of overidentification'
        if ninstr - nendog == 0:
            return InvalidTestStatistic('Test requires more instruments than '
                                        'endogenous variables.', name=name)
        stat = nobs * log(self._liml_kappa)
        df = ninstr - nendog
        null = 'The model is not overidentified.'
        return WaldTestStatistic(stat, null, df, name=name)

    @cached_property
    def basmann_f(self):
        """
        Basmann's F test of overidentifying restrictions
        
        Returns
        -------
        t : WaldTestStatistic
            Object containing test statistic, pvalue, distribution and null

        Notes
        -----
        Banmann's F test examines whether the value of :math:`\kappa`
        computed for the LIML estimator is sufficiently close to one to 
        indicate the model is not overidentified. The test statistic is
        
        .. math ::
        
          \hat{\kappa} (n -n_{instr})/q \sim F_{q, n - n_{instr}}
        
        where :math:`q = n_{instr} - n_{endog}`.
        """
        nobs, ninstr = self.model.instruments.shape
        nendog, nexog = self.model.endog.shape[1], self.model.exog.shape[1]
        name = 'Basmann\' F  test of overidentification'
        if ninstr - nendog == 0:
            return InvalidTestStatistic('Test requires more instruments than '
                                        'endogenous variables.', name=name)
        df = ninstr - nendog
        df_denom = nobs - (nexog + ninstr)
        stat = (self._liml_kappa - 1) * df_denom / df
        null = 'The model is not overidentified.'
        return WaldTestStatistic(stat, null, df, df_denom=df_denom, name=name)


class IVGMMResults(_CommonIVResults):
    """
    Results from GMM estimation of IV models

    Notes
    -----
    .. todo::

        * Hypothesis testing
    """

    def __init__(self, results, model):
        super(IVGMMResults, self).__init__(results, model)
        self._weight_mat = results['weight_mat']
        self._weight_type = results['weight_type']
        self._weight_config = results['weight_config']
        self._iterations = results['iterations']
        self._j_stat = results['j_stat']

    @property
    def weight_matrix(self):
        """Weight matrix used in the final-step GMM estimation"""
        return self._weight_mat

    @property
    def iterations(self):
        """Iterations used in GMM estimation"""
        return self._iterations

    @property
    def weight_type(self):
        """Weighting matrix method used in estimation"""
        return self._weight_type

    @property
    def weight_config(self):
        """Weighting matrix configuration used in estimation"""
        return self._weight_config

    @property
    def j_stat(self):
        r"""
        J-test of overidentifying restrictions
        
        Returns
        -------
        j : WaldTestStatistic
            J-statistic test of overidentifying restrictions
        
        Notes
        -----
        The J-statistic tests whether the moment conditions are sufficiently 
        close to zero to indicate that the model is not overidentified. The
        statistic is defined as 
        
        .. math ::
          
          n \bar{g}'W^{-1}\bar{g} \sim \chi^2_q
        
        where :math:`\bar{g} = n^{-1}\sum \hat{\epsilon}_i z_i` where 
        :math:`z_i` includes both the exogensou variables and instruments and
        :math:`\hat{\epsilon}_i` are the model residuals. :math:`W` is a consistent
        estimator of the variance of :math:`\sqrt{n}\bar{g}`. The degree of 
        freedom is :math:`q = n_{instr} - n_{endog}`. 
        """
        return self._j_stat

    def c_stat(self, vars=None):
        r"""
        C-test of endogeneity
        
        Parameters
        ----------
        vars : list(str), optional
            List of variables to test for exogeneity.  If None, all variables 
            are jointly tested. 

        Returns
        -------
        t : WaldTestStatistic
            Object containing test statistic, pvalue, distribution and null
        
        Notes
        -----
        The C statistic tests the difference between the model estimated by 
        assuming one or more of the endogenous variables is actually 
        exogenous.  The test is implemented as the difference between the 
        J-statistics of two GMM estimations where both use the same weighting
        matrix.  The use of a common weighting matrix is required for the C
        statistic to be positive.  
        
        The first model is a estimated uses GMM estimation where one or more
        of the endogenous variables are assumed to be endogenous.  The model
        would be relatively efficient if the assumption were true, and two 
        quantities are computed, the J statistic, :math:`J_e`, and the 
        moment weighting matrix, :math:`W_e`. 
        
        WLOG assume the q variables tested are in the final q positions so that
        the first :math:`n_{exog} + n_{instr}` rows and columns correspond to 
        the moment conditions in the original model. The second J statistic is 
        computed using parameters estimated using the original moment 
        conditions along with the upper left block of :math:`W_e`.  Denote this
        values as :math:`J_c` where the c is used to indicate consistent. 
        
        The test statistic is then 
        
        .. math ::
        
          J_e - J_c \sim \chi^2_{m}
          
        where :math:`m` is the number of variables whose exogeneity is being 
        tested.
        """
        dependent, instruments = self.model.dependent, self.model.instruments
        exog, endog = self.model.exog, self.model.endog
        if vars is None:
            exog_e = c_[exog.ndarray, endog.ndarray]
            nobs = exog_e.shape[0]
            endog_e = empty((nobs, 0))
            null = 'All endogenous variables are exogenous'
        else:
            if not isinstance(vars, list):
                vars = [vars]
            exog_e = c_[exog.ndarray, endog.pandas[vars].values]
            ex = [c for c in endog.pandas if c not in vars]
            endog_e = endog.pandas[ex].values
            null = 'Variables {0} are exogenous'.format(', '.join(vars))
        from linearmodels.iv import IVGMM
        mod = IVGMM(dependent, exog_e, endog_e, instruments)
        res_e = mod.fit(cov_type=self.cov_type, **self.cov_config)
        j_e = res_e.j_stat.stat

        x = self.model._x
        y = self.model._y
        z = self.model._z
        nz = z.shape[1]
        weight_mat_c = res_e.weight_matrix.values[:nz, :nz]
        params_c = mod.estimate_parameters(x, y, z, weight_mat_c)
        j_c = self.model._j_statistic(params_c, weight_mat_c).stat

        stat = j_e - j_c
        df = exog_e.shape[1] - exog.shape[1]
        return WaldTestStatistic(stat, null, df, name='C-statistic')


class FirstStageResults(object):
    """
    First stage estimation results and diagnostics
    
    .. todo ::

      * Summary
    """

    def __init__(self, dep, exog, endog, instr, cov_type, cov_config):
        self.dep = dep
        self.exog = exog
        self.endog = endog
        self.instr = instr
        reg = c_[self.exog.ndarray, self.endog.ndarray]
        self._reg = DataFrame(reg, columns=self.exog.cols + self.endog.cols)
        self._cov_type = cov_type
        self._cov_config = cov_config
        self._fitted = {}

    @cached_property
    def diagnostics(self):
        """
        Post estimation diagnostics of first-stage fit

        Returns
        -------
        res : DataFrame
            DataFrame where each endogenous variable appears as a row and
            the columns contain alternative measures.  The columns are:

            * rsquared - Rsquared from regression of endogenous on exogenous
              and instruments
            * partial.rsquared - Rsquared from regression of the exogenous
              variable on instruments where both the exogenous variable and
              the instrument have been orthogonalized to the exogenous
              regressors in the model.   
            * f.stat - Test that all coefficients are zero in the model
              used to estimate the partial rsquared. Uses a standard F-test
              when the covariance estimtor is unadjusted - otherwise uses a
              Wald test statistic with a chi2 distribution.
            * f.pval - P-value of the test that all coefficients are zero
              in the model used to estimate the partial rsquared
            * shea.rsquared - Shea's r-squared which measures the correlation
              between the projected and orthogonalized instrument on the
              orthogonoalized endogenous regressor where the orthogonalization
              is with respect to the other included variables in the model.
        """
        from linearmodels.iv.model import _OLS, IV2SLS
        endog, exog, instr = self.endog, self.exog, self.instr
        z = instr.ndarray
        x = exog.ndarray
        px = x @ pinv(x)
        ez = z - px @ z
        out = {}
        individal_results = self.individual
        for col in endog.pandas:
            inner = {}
            inner['rsquared'] = individal_results[col].rsquared
            y = endog.pandas[[col]].values
            ey = y - px @ y
            mod = _OLS(ey, ez)
            res = mod.fit(self._cov_type, **self._cov_config)
            inner['partial.rsquared'] = res.rsquared
            params = res.params.values
            params = params[:, None]
            stat = params.T @ inv(res.cov) @ params
            stat = stat.squeeze()
            w = WaldTestStatistic(stat, null='', df=params.shape[0])
            inner['f.stat'] = w.stat
            inner['f.pval'] = w.pval
            out[col] = Series(inner)
        out = DataFrame(out).T

        dep = self.dep
        r2sls = IV2SLS(dep, exog, endog, instr).fit('unadjusted')
        rols = _OLS(dep, self._reg).fit('unadjusted')
        shea = (rols.std_errors / r2sls.std_errors) ** 2
        shea *= (1 - r2sls.rsquared) / (1 - rols.rsquared)
        out['shea.rsquared'] = shea[out.index]
        cols = ['rsquared', 'partial.rsquared', 'shea.rsquared', 'f.stat', 'f.pval']
        out = out[cols]
        return out

    @cached_property
    def individual(self):
        """
        Individual model results from first-stage regressions

        Returns
        -------
        res : dict
            Dictionary containing first stage estimation results. Keys are
            the variable names of the endogenous regressors.
        """
        from linearmodels.iv.model import _OLS
        exog_instr = c_[self.exog.ndarray, self.instr.ndarray]
        res = {}
        for col in self.endog.pandas:
            mod = _OLS(self.endog.pandas[col], exog_instr)
            res[col] = mod.fit(self._cov_type, **self._cov_config)

        return res